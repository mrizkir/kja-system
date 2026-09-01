"""TFT production inference for dissolved oxygen."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from config import Config
from training.device import apply_runtime_accelerator
from training.evaluate import forecast_columns
from training.preprocess import (
    DEFAULT_ENCODER_LENGTH,
    FUTR_EXOG,
    HIST_EXOG,
    HORIZONS,
    build_futr_frame,
    readings_to_nf_frame,
)

logger = logging.getLogger("kja.inference")

_nf = None
_meta: dict | None = None
_load_error: str | None = None
_tried_load = False


def artifact_dir() -> Path:
    return Path(Config.TFT_ARTIFACT_DIR)


def _meta_path() -> Path:
    return artifact_dir().parent / "tft_v1_meta.json"


def _metrics_path() -> Path:
    return artifact_dir().parent / "tft_v1_metrics.json"


def _empty_quantiles() -> dict:
    return {"q10": None, "q50": None, "q90": None}


def _empty_result(latency_ms: float, error: str) -> dict:
    return {
        "do_now": None,
        "do_6h": _empty_quantiles(),
        "do_24h": _empty_quantiles(),
        "do_7d": _empty_quantiles(),
        "confidence": None,
        "latency_ms": latency_ms,
        "error": error,
    }


def _confidence_from_metrics() -> float:
    path = _metrics_path()
    if not path.is_file():
        return 0.0
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        mapes = [r["mape"] for r in rows if r.get("mape") is not None]
        if not mapes:
            return 0.0
        return round(max(0.0, min(1.0, 1.0 - (sum(mapes) / len(mapes)) / 100.0)), 4)
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return 0.0


def _load_model() -> None:
    global _nf, _meta, _load_error, _tried_load
    if _tried_load:
        return
    _tried_load = True
    path = artifact_dir()
    if not path.exists():
        _load_error = (
            f"TFT artifact not found at {path}. "
            "Train with: python training/train_tft.py --data <csv>"
        )
        logger.warning(_load_error)
        return
    try:
        from neuralforecast import NeuralForecast

        _nf = NeuralForecast.load(path=str(path))
        apply_runtime_accelerator(_nf)
        if _meta_path().is_file():
            _meta = json.loads(_meta_path().read_text(encoding="utf-8"))
    except Exception as exc:
        _load_error = f"Failed to load TFT artifact at {path}: {exc}"
        logger.exception(_load_error)
        _nf = None


def _step_value(values: list[float], horizon: int) -> float:
    idx = horizon - 1
    if idx < 0 or idx >= len(values):
        raise ValueError(
            f"Forecast length {len(values)} is shorter than horizon +{horizon}h"
        )
    return round(float(values[idx]), 2)


def _forecast_at_horizon(
    fcst: pd.DataFrame,
    last_ds: pd.Timestamp,
    pred_col: str,
    horizon: int,
) -> float:
    target = pd.Timestamp(last_ds) + pd.Timedelta(hours=int(horizon))
    match = fcst.loc[fcst["ds"] == target, pred_col]
    if not match.empty:
        return round(float(match.iloc[0]), 2)
    values = [float(v) for v in fcst.sort_values("ds")[pred_col].tolist()]
    return _step_value(values, horizon)


def _quantile_at_horizon(
    fcst: pd.DataFrame,
    last_ds: pd.Timestamp,
    point_col: str,
    lo_col: str | None,
    hi_col: str | None,
    horizon: int,
) -> dict:
    return {
        "q10": _forecast_at_horizon(fcst, last_ds, lo_col, horizon) if lo_col else None,
        "q50": _forecast_at_horizon(fcst, last_ds, point_col, horizon),
        "q90": _forecast_at_horizon(fcst, last_ds, hi_col, horizon) if hi_col else None,
    }


def _last_known_rainfall(frame: pd.DataFrame) -> float:
    if "rainfall_forecast_mm" not in frame.columns:
        return 0.0
    hist = frame["rainfall_forecast_mm"].dropna()
    if hist.empty:
        return 0.0
    return float(hist.iloc[-1])


def _rainfall_for_horizon(
    future_timestamps: list,
    future_rainfall_mm: list[dict] | None,
    last_known: float,
) -> tuple[list[float], bool]:
    rain_map: dict[pd.Timestamp, float] = {}
    if future_rainfall_mm:
        for item in future_rainfall_mm:
            ts = pd.to_datetime(item.get("timestamp"), errors="coerce")
            val = item.get("rainfall_forecast_mm")
            if pd.isna(ts) or val is None:
                continue
            ts = pd.Timestamp(ts)
            if ts.tzinfo is not None:
                ts = pd.Timestamp(
                    ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
                )
            rain_map[ts] = float(val)
            rain_map[ts.floor("h")] = float(val)

    values: list[float] = []
    used_fallback = not future_rainfall_mm
    for ts in future_timestamps:
        key = pd.Timestamp(ts)
        if key in rain_map:
            values.append(rain_map[key])
        elif key.floor("h") in rain_map:
            values.append(rain_map[key.floor("h")])
        else:
            values.append(last_known)
            used_fallback = True
    return values, used_fallback


def predict_do(
    kja_id: int,
    readings: list[dict],
    static: dict[str, object] | None = None,
    future_rainfall_mm: list[dict] | None = None,
) -> dict:
    """Forecast DO quantiles (Q10/Q50/Q90) at +6h, +24h, +7d.

    Each horizon field is ``{q10, q50, q90}``. Point-accuracy consumers
    should use ``q50``. On missing artifact or inference failure, quantile
    fields are null and ``error`` explains why.
    """
    start = time.perf_counter()
    _load_model()
    if _nf is None:
        latency = round((time.perf_counter() - start) * 1000, 1)
        return _empty_result(latency, _load_error or "TFT model is not available")

    encoder_length = int(
        (_meta or {}).get("encoder_length", Config.TFT_ENCODER_HOURS)
        or DEFAULT_ENCODER_LENGTH
    )
    frame = readings_to_nf_frame(kja_id, readings, static=static)
    if frame.empty:
        latency = round((time.perf_counter() - start) * 1000, 1)
        return _empty_result(
            latency,
            "No usable sensor history for TFT (need timestamps and DO values)",
        )

    frame = frame.tail(encoder_length)
    if "rainfall_forecast_mm" not in frame.columns:
        frame["rainfall_forecast_mm"] = 0.0
    else:
        frame["rainfall_forecast_mm"] = frame["rainfall_forecast_mm"].fillna(0.0)
    try:
        predict_kwargs: dict = {"df": frame}
        stat_exog = (_meta or {}).get("stat_exog") or []
        if stat_exog:
            present = [c for c in stat_exog if c in frame.columns]
            if present:
                static_df = frame[["unique_id", *present]].drop_duplicates("unique_id")
                frame = frame.drop(columns=present)
                predict_kwargs["static_df"] = static_df
        hist_exog = (_meta or {}).get("hist_exog")
        futr_exog = (_meta or {}).get("futr_exog")
        if not hist_exog:
            hist_exog = [c for c in HIST_EXOG if c in frame.columns]
        if not futr_exog:
            futr_exog = [c for c in FUTR_EXOG if c in frame.columns]
        keep = ["unique_id", "ds", "y", *hist_exog]
        keep.extend(c for c in futr_exog if c not in keep)
        frame = frame[[c for c in keep if c in frame.columns]]
        predict_kwargs["df"] = frame
        if futr_exog:
            h_max = int((_meta or {}).get("horizon") or max(HORIZONS))
            last_ds = pd.Timestamp(frame["ds"].iloc[-1])
            future_ts = [last_ds + pd.Timedelta(hours=i) for i in range(1, h_max + 1)]
            rain_vals, used_fallback = _rainfall_for_horizon(
                future_ts,
                future_rainfall_mm,
                _last_known_rainfall(frame),
            )
            if used_fallback:
                logger.warning(
                    "rainfall_forecast_mm incomplete for the +%sh horizon; "
                    "repeating last known value as a placeholder pending BMKG integration",
                    h_max,
                )
            predict_kwargs["futr_df"] = build_futr_frame(
                str(frame["unique_id"].iloc[-1]),
                future_ts,
                rain_vals,
            )
        fcst = _nf.predict(**predict_kwargs)
        fcst = fcst.reset_index() if "ds" not in fcst.columns else fcst
        fcst = fcst.sort_values("ds")
        point_col, lo_col, hi_col = forecast_columns(fcst)
        last_ds = pd.Timestamp(frame["ds"].iloc[-1])
        result = {
            "do_now": round(float(frame["y"].iloc[-1]), 2),
            "do_6h": _quantile_at_horizon(
                fcst, last_ds, point_col, lo_col, hi_col, HORIZONS[0]
            ),
            "do_24h": _quantile_at_horizon(
                fcst, last_ds, point_col, lo_col, hi_col, HORIZONS[1]
            ),
            "do_7d": _quantile_at_horizon(
                fcst, last_ds, point_col, lo_col, hi_col, HORIZONS[2]
            ),
            "confidence": _confidence_from_metrics(),
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
        return result
    except Exception as exc:
        latency = round((time.perf_counter() - start) * 1000, 1)
        logger.exception("TFT predict failed")
        return _empty_result(latency, f"TFT inference failed: {exc}")
