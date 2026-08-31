"""Shared load, resample, and chronological split for TFT and LSTM.

The pipeline defines the dataset contract. Any CSV (including
``dataset_madong.csv``) must satisfy it — the code is not tuned to the
short practice sample.
"""

from __future__ import annotations

import math
import logging
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = (
    "kja_id",
    "timestamp",
    "ph",
    "temperature",
    "salinity",
    "turbidity",
    "light_intensity",
    "do_observed",
    "rainfall_forecast_mm",
)
HIST_EXOG = (
    "ph",
    "temperature",
    "salinity",
    "turbidity",
    "light_intensity",
)
FUTR_EXOG = ("rainfall_forecast_mm",)
OPTIONAL_STATIC = ("species",)
HORIZONS = (6, 24, 168)
DEFAULT_ENCODER_LENGTH = 336
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15
FREQ = "h"
CSV_SEP = ";"

logger = logging.getLogger("kja.training")


class InsufficientDataError(ValueError):
    """Raised when a series is too short for encoder length + max horizon."""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_dataset_path() -> Path:
    return Path(__file__).resolve().parent / "dataset_madong.csv"


def artifacts_dir() -> Path:
    path = Path(__file__).resolve().parent / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def min_series_hours(encoder_length: int, max_horizon: int) -> int:
    """Minimum hourly points per series so the 70% train split can form one window."""
    min_train = encoder_length + max_horizon
    return math.ceil(min_train / TRAIN_RATIO)


def load_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = pd.read_csv(path, sep=CSV_SEP)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Dataset is missing required columns: "
            f"{missing}. Expected: {list(REQUIRED_COLUMNS)}"
        )

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if df["timestamp"].isna().any():
        n_bad = int(df["timestamp"].isna().sum())
        raise ValueError(
            f"{n_bad} row(s) have invalid timestamps; "
            "use YYYY-MM-DD HH:MM:SS"
        )

    df["kja_id"] = df["kja_id"].astype(str)
    n_dup = int(df.duplicated(subset=["kja_id", "timestamp"]).sum())
    if n_dup:
        df = df.drop_duplicates(subset=["kja_id", "timestamp"], keep="last")

    return df.sort_values(["kja_id", "timestamp"]).reset_index(drop=True)


def resample_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw high-frequency readings to hourly means per kja_id."""
    static_cols = [c for c in OPTIONAL_STATIC if c in df.columns]
    static_map = (
        df.groupby("kja_id", sort=False)[static_cols].first()
        if static_cols
        else None
    )

    parts: list[pd.DataFrame] = []
    for uid, group in df.groupby("kja_id", sort=False):
        hourly = (
            group.set_index("timestamp")
            .sort_index()
            .resample(FREQ)
            .mean(numeric_only=True)
        )
        hourly = hourly.interpolate(method="time", limit=3)
        hourly = hourly.dropna(subset=["do_observed"])
        if hourly.empty:
            continue
        hourly["kja_id"] = uid
        hourly = hourly.reset_index()
        parts.append(hourly)

    if not parts:
        raise InsufficientDataError(
            "Resampling to hourly produced no rows. "
            "Check timestamps and do_observed values."
        )

    out = pd.concat(parts, ignore_index=True)
    if static_map is not None:
        out = out.merge(static_map, on="kja_id", how="left")
    return out.sort_values(["kja_id", "timestamp"]).reset_index(drop=True)


def validate_volume(
    hourly: pd.DataFrame,
    encoder_length: int,
    max_horizon: int,
) -> None:
    """Fail if any series is too short for encoder + max horizon under 70/15/15."""
    min_train = encoder_length + max_horizon
    min_total = min_series_hours(encoder_length, max_horizon)
    short: list[str] = []
    for uid, group in hourly.groupby("kja_id"):
        n = len(group)
        if n < min_total:
            short.append(f"kja_id={uid}: {n} hourly rows")

    if short:
        raise InsufficientDataError(
            "Insufficient hourly data for encoder_length "
            f"{encoder_length} + max_horizon {max_horizon}. "
            f"Need at least {min_total} hourly points per series "
            f"(so the {int(TRAIN_RATIO * 100)}% train split has "
            f">= {min_train} hours). Too short:\n  - "
            + "\n  - ".join(short)
            + "\nReplace the CSV with a dataset that meets this contract; "
            "do not shorten the encoder or horizons to fit a sample file."
        )


def to_nf_frame(hourly: pd.DataFrame) -> pd.DataFrame:
    """Map contract columns to neuralforecast ``unique_id``, ``ds``, ``y``."""
    frame = hourly.rename(
        columns={"kja_id": "unique_id", "timestamp": "ds", "do_observed": "y"}
    )
    keep = ["unique_id", "ds", "y", *HIST_EXOG]
    keep.extend(c for c in FUTR_EXOG if c in frame.columns)
    keep.extend(c for c in OPTIONAL_STATIC if c in frame.columns)
    return frame[keep].sort_values(["unique_id", "ds"]).reset_index(drop=True)


def chronological_split(
    nf_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """70/15/15 time-based split per series. Never shuffled."""
    trains, vals, tests = [], [], []
    for _, group in nf_df.groupby("unique_id", sort=False):
        group = group.sort_values("ds")
        n = len(group)
        n_train = int(n * TRAIN_RATIO)
        n_val = int(n * VAL_RATIO)
        trains.append(group.iloc[:n_train])
        vals.append(group.iloc[n_train : n_train + n_val])
        tests.append(group.iloc[n_train + n_val :])

    train = pd.concat(trains, ignore_index=True)
    val = pd.concat(vals, ignore_index=True)
    test = pd.concat(tests, ignore_index=True)
    return train, val, test


def load_and_prepare(
    path: str | Path,
    encoder_length: int = DEFAULT_ENCODER_LENGTH,
    horizons: tuple[int, ...] = HORIZONS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Load CSV → hourly NF frame → chronological split.

    Returns train, val, test, and static covariate names present in the file.
    """
    logger.info("Loading dataset %s", path)
    raw = load_csv(path)
    n_series = raw["kja_id"].nunique()
    logger.info(
        "Loaded %s raw rows, %s series, span %s → %s",
        len(raw),
        n_series,
        raw["timestamp"].min(),
        raw["timestamp"].max(),
    )
    logger.info("Resampling to hourly frequency")
    hourly = resample_hourly(raw)
    logger.info(
        "Hourly series: %s rows across %s kja_id(s)",
        len(hourly),
        hourly["kja_id"].nunique(),
    )
    logger.info(
        "Checking volume (need ≥ %s hourly points per series)",
        min_series_hours(encoder_length, max(horizons)),
    )
    validate_volume(hourly, encoder_length, max(horizons))
    nf_df = to_nf_frame(hourly)
    static_names = [c for c in OPTIONAL_STATIC if c in nf_df.columns]
    train, val, test = chronological_split(nf_df)
    logger.info(
        "Split 70/15/15: train=%s val=%s test=%s",
        len(train),
        len(val),
        len(test),
    )
    return train, val, test, static_names


def readings_to_nf_frame(
    kja_id: int,
    readings: list[dict],
    static: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Convert API history dicts to an hourly neuralforecast frame."""
    empty_cols = ["unique_id", "ds", "y", *HIST_EXOG, *FUTR_EXOG]
    if not readings:
        return pd.DataFrame(columns=empty_cols)

    rows = []
    for item in readings:
        y = item.get("do_observed", item.get("do_predicted"))
        ts = pd.to_datetime(item.get("timestamp"), errors="coerce")
        if pd.isna(ts) or y is None:
            continue
        rain = item.get("rainfall_forecast_mm")
        row = {
            "kja_id": str(kja_id),
            "timestamp": ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts,
            "ph": item.get("ph"),
            "temperature": item.get("temperature"),
            "salinity": item.get("salinity"),
            "turbidity": item.get("turbidity"),
            "light_intensity": item.get("light_intensity"),
            "do_observed": float(y),
            "rainfall_forecast_mm": None if rain is None else float(rain),
        }
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=empty_cols)

    df = pd.DataFrame(rows)
    hourly = resample_hourly(df)
    frame = to_nf_frame(hourly)
    if static:
        for key, value in static.items():
            if key in OPTIONAL_STATIC:
                frame[key] = value
    return frame


def build_futr_frame(
    unique_id: str,
    future_timestamps: list,
    rainfall_values: list[float] | None,
) -> pd.DataFrame:
    """Build NeuralForecast ``futr_df`` for rainfall over future timestamps."""
    timestamps = pd.to_datetime(future_timestamps)
    n = len(timestamps)
    if rainfall_values is None:
        values: list[float | None] = [None] * n
    elif len(rainfall_values) < n:
        values = list(rainfall_values) + [None] * (n - len(rainfall_values))
    else:
        values = list(rainfall_values[:n])
    return pd.DataFrame(
        {
            "unique_id": str(unique_id),
            "ds": timestamps,
            "rainfall_forecast_mm": values,
        }
    )
