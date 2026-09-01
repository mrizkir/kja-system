"""Weiss (1970) DO solubility baseline + residual calibration against Lutron.

Two-stage soft-sensor, upstream of the TFT/LSTM forecasting pipeline:

    Weiss(1970) from (temperature, salinity)  -> theoretical saturation solubility
    Lutron field readings (sparse, ~3x/week)  -> residual = lutron - weiss
    smooth correction(t) fit on residuals     -> diurnal (hour-of-day) + slow trend
    do_observed(t) = Weiss(t) + correction(t) -> written for every hourly row

Only numpy/pandas are used (no scipy/sklearn in this project's requirements).

Each field visit yields 6 CONSECUTIVE hourly Lutron readings (one "block").
Points within a block are strongly autocorrelated (DO at hour 21 is nearly
identical to hour 20), so all splitting here (CV folds and the held-out
test set) is done at the VISIT level via ``visit_no`` -- an entire block
moves together into train or test, never split across the boundary. Point-
level random splitting would leak near-duplicate observations across the
train/test boundary and inflate apparent accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.preprocess import CSV_SEP

WEISS_A = (-173.4292, 249.6339, 143.3483, -21.8492)
WEISS_B = (-0.033096, 0.014259, -0.0017000)
ML_TO_MG_L = 1.42905


def weiss_1970_do_mg_l(temp_c, salinity_ppt):
    """Oxygen solubility (mg/L) at 100% saturation, Weiss (1970)."""
    t_k = np.asarray(temp_c, dtype=float) + 273.15
    s = np.asarray(salinity_ppt, dtype=float)
    a1, a2, a3, a4 = WEISS_A
    b1, b2, b3 = WEISS_B
    ln_c = (
        a1
        + a2 * (100.0 / t_k)
        + a3 * np.log(t_k / 100.0)
        + a4 * (t_k / 100.0)
        + s * (b1 + b2 * (t_k / 100.0) + b3 * (t_k / 100.0) ** 2)
    )
    return np.exp(ln_c) * ML_TO_MG_L


def load_lutron_log(path: str | Path) -> pd.DataFrame:
    """Load a calibration log: ``visit_no;timestamp;do_lutron_mg_l`` (semicolon-delimited).

    ``visit_no`` identifies which 6-hour field visit a reading belongs to
    (see ``training/lutron_log_template.csv``) -- required so splitting can
    keep each visit's block intact instead of shuffling individual hours.
    """
    df = pd.read_csv(path, sep=CSV_SEP)
    missing = {"visit_no", "timestamp", "do_lutron_mg_l"} - set(df.columns)
    if missing:
        raise ValueError(f"Lutron log missing columns: {sorted(missing)}")
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if df["timestamp"].isna().any():
        raise ValueError("Lutron log has invalid timestamps; use YYYY-MM-DD HH:MM:SS")
    df["do_lutron_mg_l"] = pd.to_numeric(df["do_lutron_mg_l"], errors="coerce")
    if df["do_lutron_mg_l"].isna().any():
        raise ValueError("Lutron log has non-numeric do_lutron_mg_l value(s)")
    return df.sort_values("timestamp").reset_index(drop=True)


def _design_matrix(
    timestamps: pd.Series,
    study_start: pd.Timestamp,
    n_harmonics: int,
    trend_degree: int,
) -> np.ndarray:
    ts = pd.DatetimeIndex(timestamps)
    hour_frac = ts.hour + ts.minute / 60.0
    day_index = (ts - study_start).total_seconds() / 86400.0

    cols = [np.ones(len(ts))]
    for k in range(1, n_harmonics + 1):
        angle = 2 * np.pi * k * hour_frac / 24.0
        cols.append(np.sin(angle))
        cols.append(np.cos(angle))
    for d in range(1, trend_degree + 1):
        cols.append(day_index**d)
    return np.column_stack(cols)


class CorrectionModel:
    def __init__(self, coef: np.ndarray, study_start: pd.Timestamp, n_harmonics: int, trend_degree: int):
        self.coef = coef
        self.study_start = study_start
        self.n_harmonics = n_harmonics
        self.trend_degree = trend_degree

    def predict(self, timestamps: pd.Series) -> np.ndarray:
        x = _design_matrix(timestamps, self.study_start, self.n_harmonics, self.trend_degree)
        return x @ self.coef

    def to_dict(self) -> dict:
        return {
            "coef": self.coef.tolist(),
            "study_start": self.study_start.isoformat(),
            "n_harmonics": self.n_harmonics,
            "trend_degree": self.trend_degree,
        }


def fit_correction_model(
    calib: pd.DataFrame,
    study_start: pd.Timestamp,
    n_harmonics: int = 2,
    trend_degree: int = 2,
) -> CorrectionModel:
    """Least-squares fit of correction(t) on Lutron-minus-Weiss residuals.

    ``calib`` must have ``timestamp`` and ``residual`` columns.
    """
    x = _design_matrix(calib["timestamp"], study_start, n_harmonics, trend_degree)
    coef, *_ = np.linalg.lstsq(x, calib["residual"].to_numpy(), rcond=None)
    return CorrectionModel(coef, study_start, n_harmonics, trend_degree)


def _score(calib: pd.DataFrame, pred_do: np.ndarray) -> dict:
    true_do = calib["do_lutron_mg_l"].to_numpy()
    err = pred_do - true_do
    if err.size < 2:
        return {"n": int(err.size), "rmse": None, "mae": None, "r2": None}
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((true_do - true_do.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    return {
        "n": int(err.size),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "r2": round(r2, 4) if r2 is not None else None,
    }


def visit_level_split(
    calib: pd.DataFrame, test_frac: float = 0.25, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split calibration points 75/25 by ``visit_no``, never splitting a block.

    A held-out visit contributes none of its 6 hourly points to fitting --
    matches the advisor's split (39 visits calibration / 13 visits test for
    52 total visits).
    """
    visits = calib["visit_no"].unique()
    rng = np.random.default_rng(seed)
    rng.shuffle(visits)
    n_test = max(1, round(len(visits) * test_frac))
    test_visits = set(visits[:n_test])
    test_df = calib[calib["visit_no"].isin(test_visits)].reset_index(drop=True)
    train_df = calib[~calib["visit_no"].isin(test_visits)].reset_index(drop=True)
    return train_df, test_df


def blocked_k_fold_cv(
    calib: pd.DataFrame,
    study_start: pd.Timestamp,
    n_harmonics: int = 2,
    trend_degree: int = 2,
    k: int = 5,
    seed: int = 42,
) -> dict:
    """K-fold CV grouped by ``visit_no`` -- whole blocks move together.

    Used only as an internal diagnostic on the calibration pool (e.g. for
    choosing n_harmonics/trend_degree); the number reported to the thesis
    should be the single held-out split from ``visit_level_split``.
    """
    visits = calib["visit_no"].unique()
    rng = np.random.default_rng(seed)
    rng.shuffle(visits)
    folds = np.array_split(visits, min(k, len(visits)))

    pred_do_all: list[np.ndarray] = []
    test_frames: list[pd.DataFrame] = []
    for fold in folds:
        fold_visits = set(fold.tolist())
        test_df = calib[calib["visit_no"].isin(fold_visits)]
        train_df = calib[~calib["visit_no"].isin(fold_visits)]
        if len(train_df) < 3 or test_df.empty:
            continue
        model = fit_correction_model(train_df, study_start, n_harmonics, trend_degree)
        pred_correction = model.predict(test_df["timestamp"])
        pred_do_all.append(test_df["weiss_do"].to_numpy() + pred_correction)
        test_frames.append(test_df)

    if not test_frames:
        return {"n": 0, "rmse": None, "mae": None, "r2": None}
    pooled_test = pd.concat(test_frames, ignore_index=True)
    return _score(pooled_test, np.concatenate(pred_do_all))


def build_calibration_frame(sensor_df: pd.DataFrame, lutron_df: pd.DataFrame) -> pd.DataFrame:
    """Match each Lutron reading to the sensor row at the same hour and compute residuals.

    ``sensor_df`` must already be at hourly resolution (one row per hour) with
    ``timestamp``, ``temperature``, ``salinity`` columns.
    """
    sensor_hourly = sensor_df.copy()
    sensor_hourly["timestamp"] = pd.to_datetime(sensor_hourly["timestamp"])
    sensor_hourly = sensor_hourly.set_index("timestamp")

    rows = []
    unmatched = []
    for _, r in lutron_df.iterrows():
        ts = pd.Timestamp(r["timestamp"]).floor("h")
        if ts not in sensor_hourly.index:
            unmatched.append(r["timestamp"])
            continue
        sensor_row = sensor_hourly.loc[ts]
        weiss_do = float(weiss_1970_do_mg_l(sensor_row["temperature"], sensor_row["salinity"]))
        rows.append(
            {
                "visit_no": r["visit_no"],
                "timestamp": ts,
                "do_lutron_mg_l": float(r["do_lutron_mg_l"]),
                "weiss_do": weiss_do,
                "residual": float(r["do_lutron_mg_l"]) - weiss_do,
            }
        )

    if unmatched:
        raise ValueError(
            f"{len(unmatched)} Lutron timestamp(s) have no matching hourly sensor row "
            f"(no ph/temperature/salinity reading at that hour): {unmatched[:5]}..."
        )

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def within_visit_horizon_pairs(calib: pd.DataFrame) -> pd.DataFrame:
    """Real (reference_hour -> +N h actual) pairs from each 6-point visit block.

    A visit's 6 consecutive hourly points span 5 hours end-to-end, so the
    lags available here are +1h..+5h -- NOT +6h. Use these to validate a
    forecaster's short-horizon output against genuine consecutive Lutron
    measurements (stronger than isolated points), while +6h/+24h/+7d still
    validate against the calibrated do_observed(t) series.
    """
    rows = []
    for visit_no, block in calib.groupby("visit_no"):
        block = block.sort_values("timestamp").reset_index(drop=True)
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                lag_h = int((block["timestamp"].iloc[j] - block["timestamp"].iloc[i]).total_seconds() // 3600)
                rows.append(
                    {
                        "visit_no": visit_no,
                        "ref_timestamp": block["timestamp"].iloc[i],
                        "target_timestamp": block["timestamp"].iloc[j],
                        "lag_hours": lag_h,
                        "ref_do_lutron_mg_l": block["do_lutron_mg_l"].iloc[i],
                        "target_do_lutron_mg_l": block["do_lutron_mg_l"].iloc[j],
                    }
                )
    return pd.DataFrame(rows)


def calibrate_dataset(
    sensor_path: str | Path,
    lutron_path: str | Path,
    output_path: str | Path,
    n_harmonics: int = 2,
    trend_degree: int = 2,
    test_frac: float = 0.25,
    seed: int = 42,
    report_path: str | Path | None = None,
    pairs_path: str | Path | None = None,
) -> tuple[pd.DataFrame, dict]:
    sensor_df = pd.read_csv(sensor_path, sep=CSV_SEP)
    sensor_df["timestamp"] = pd.to_datetime(sensor_df["timestamp"])
    lutron_df = load_lutron_log(lutron_path)

    calib = build_calibration_frame(sensor_df, lutron_df)
    study_start = calib["timestamp"].min()
    n_visits = calib["visit_no"].nunique()

    # 1) Visit-level 75/25 split -> the honest, reportable generalization number.
    #    A held-out visit's points never touch the model used to score it.
    calib_pool, held_out = visit_level_split(calib, test_frac=test_frac, seed=seed)
    holdout_model = fit_correction_model(calib_pool, study_start, n_harmonics, trend_degree)
    holdout_pred = held_out["weiss_do"].to_numpy() + holdout_model.predict(held_out["timestamp"])
    holdout_metrics = _score(held_out, holdout_pred)

    # 2) Blocked k-fold CV within the calibration pool only -- diagnostic for
    #    choosing n_harmonics/trend_degree; never touches the held-out set.
    cv = blocked_k_fold_cv(calib_pool, study_start, n_harmonics=n_harmonics, trend_degree=trend_degree)

    # 3) Refit on ALL calibration points (pool + held-out) for the correction
    #    actually applied to the output dataset -- maximizes data used for the
    #    deployed do_observed(t), separate from the honest accuracy estimate above.
    final_model = fit_correction_model(calib, study_start, n_harmonics=n_harmonics, trend_degree=trend_degree)

    weiss_all = weiss_1970_do_mg_l(sensor_df["temperature"], sensor_df["salinity"])
    correction_all = final_model.predict(sensor_df["timestamp"])
    do_final = np.clip(weiss_all + correction_all, 0.0, None)

    out = sensor_df.copy()
    out["do_observed"] = np.round(do_final, 2)
    out.to_csv(output_path, sep=CSV_SEP, index=False)

    pairs = within_visit_horizon_pairs(calib)
    if pairs_path is not None and not pairs.empty:
        pairs.to_csv(pairs_path, sep=CSV_SEP, index=False)

    report = {
        "n_calibration_points": len(calib),
        "n_visits": int(n_visits),
        "n_calibration_pool_visits": int(calib_pool["visit_no"].nunique()),
        "n_held_out_visits": int(held_out["visit_no"].nunique()),
        "n_harmonics": n_harmonics,
        "trend_degree": trend_degree,
        "study_start": study_start.isoformat(),
        "holdout_split_by_visit": holdout_metrics,
        "blocked_cv_on_calibration_pool": cv,
        "within_visit_pairs_available_for_horizons_h": sorted(pairs["lag_hours"].unique().tolist()) if not pairs.empty else [],
        "residual_summary": {
            "mean": round(float(calib["residual"].mean()), 4),
            "std": round(float(calib["residual"].std()), 4),
            "min": round(float(calib["residual"].min()), 4),
            "max": round(float(calib["residual"].max()), 4),
        },
        "note": (
            "holdout_split_by_visit is the number to report as calibration "
            "accuracy (entire visits held out, never seen during fitting). "
            "The do_observed column in the output was produced by a model "
            "refit on all calibration points (pool + held-out) to make best "
            "use of the data collected; that refit model is not what "
            "holdout_split_by_visit scores."
        ),
    }
    if report_path is not None:
        Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")

    return out, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor-data", type=Path, required=True, help="Hourly sensor CSV (no do_observed needed)")
    parser.add_argument("--lutron-log", type=Path, required=True, help="visit_no;timestamp;do_lutron_mg_l CSV")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--pairs-output", type=Path, default=None, help="within-visit +1h..+5h validation pairs CSV")
    parser.add_argument("--n-harmonics", type=int, default=2)
    parser.add_argument("--trend-degree", type=int, default=2)
    parser.add_argument("--test-frac", type=float, default=0.25, help="Held-out visit fraction")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    _, report = calibrate_dataset(
        args.sensor_data,
        args.lutron_log,
        args.output,
        n_harmonics=args.n_harmonics,
        trend_degree=args.trend_degree,
        test_frac=args.test_frac,
        seed=args.seed,
        report_path=args.report,
        pairs_path=args.pairs_output,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
