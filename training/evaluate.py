"""Per-horizon metrics and Chapter 4 comparison table.

Each horizon is scored separately (never averaged across horizons).
Operational mapping (Lim et al., 2021): +6h emergency, +24h preventive,
+7d strategic planning — a miss on one horizon must stay visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from training.preprocess import HORIZONS, artifacts_dir, build_futr_frame
import logging

logger = logging.getLogger("kja.training")

R2_THRESHOLD = 0.85
MAPE_THRESHOLD = 10.0
HORIZON_LABELS = {6: "6h", 24: "24h", 168: "7d"}
COMPARISON_CSV = "comparison_v1.csv"
COMPARISON_MD = "comparison_v1.md"


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size < 2:
        return float("nan")
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size == 0:
        return float("nan")
    denom = np.abs(y_true)
    mask = denom > 1e-8
    if not np.any(mask):
        return float("nan")
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100.0)


def metrics_for_horizon(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    r2 = _r2(y_true, y_pred)
    rmse = _rmse(y_true, y_pred)
    mape = _mape(y_true, y_pred)
    passed = (
        y_true.size > 0
        and not np.isnan(r2)
        and not np.isnan(mape)
        and r2 > R2_THRESHOLD
        and mape < MAPE_THRESHOLD
    )
    return {
        "r2": None if np.isnan(r2) else round(r2, 4),
        "rmse": None if np.isnan(rmse) else round(rmse, 4),
        "mape": None if np.isnan(mape) else round(mape, 4),
        "n": int(y_true.size),
        "pass": "PASS" if passed else "FAIL",
    }


def rolling_evaluate(
    nf,
    history: pd.DataFrame,
    test: pd.DataFrame,
    encoder_length: int,
    horizons: tuple[int, ...] = HORIZONS,
    step_size: int = 6,
    static_df: pd.DataFrame | None = None,
    has_futr_exog: bool = False,
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Walk-forward eval on the test split; returns {horizon: (y_true, y_pred)}."""
    h_max = max(horizons)
    full = pd.concat([history, test], ignore_index=True)
    n_series = full["unique_id"].nunique()
    logger.info(
        "Walk-forward eval: %s series, encoder=%s, h_max=%s, step_size=%s",
        n_series,
        encoder_length,
        h_max,
        step_size,
    )
    collected: dict[int, tuple[list[float], list[float]]] = {
        hz: ([], []) for hz in horizons
    }
    n_failed = 0
    n_attempted = 0

    for uid, series in full.groupby("unique_id", sort=False):
        series = series.sort_values("ds").reset_index(drop=True)
        test_uid = test.loc[test["unique_id"] == uid]
        if test_uid.empty:
            continue
        test_start = test_uid["ds"].min()
        hist_uid = history.loc[history["unique_id"] == uid, "ds"]
        hist_end = hist_uid.max() if not hist_uid.empty else test_start - pd.Timedelta(hours=1)
        last_ds = series["ds"].max()
        origin_mask = (series["ds"] >= hist_end) & (
            series["ds"] <= last_ds - pd.Timedelta(hours=h_max)
        )
        origins = series.loc[origin_mask, "ds"].iloc[::step_size]
        pred_col = None

        for origin in origins:
            window = series[series["ds"] <= origin].tail(encoder_length)
            if window.empty:
                continue
            n_attempted += 1
            try:
                predict_kwargs = {"df": window}
                if static_df is not None:
                    predict_kwargs["static_df"] = static_df[
                        static_df["unique_id"].astype(str) == str(uid)
                    ]
                if has_futr_exog:
                    future_ts = [
                        origin + pd.Timedelta(hours=i) for i in range(1, h_max + 1)
                    ]
                    rain: list[float] = []
                    rain_col = (
                        series["rainfall_forecast_mm"]
                        if "rainfall_forecast_mm" in series.columns
                        else None
                    )
                    for ts in future_ts:
                        if rain_col is None:
                            rain.append(float("nan"))
                            continue
                        match = series.loc[series["ds"] == ts, "rainfall_forecast_mm"]
                        rain.append(
                            float(match.iloc[0])
                            if not match.empty and pd.notna(match.iloc[0])
                            else float("nan")
                        )
                    predict_kwargs["futr_df"] = build_futr_frame(
                        str(uid), future_ts, rain
                    )
                fcst = nf.predict(**predict_kwargs)
            except Exception:
                n_failed += 1
                logger.exception(
                    "Walk-forward predict failed unique_id=%s origin=%s",
                    uid,
                    origin,
                )
                continue
            fcst = fcst[fcst["unique_id"].astype(str) == str(uid)].sort_values("ds")
            if fcst.empty:
                n_failed += 1
                logger.warning(
                    "Empty forecast unique_id=%s origin=%s", uid, origin
                )
                continue
            if pred_col is None:
                pred_col = [c for c in fcst.columns if c not in ("unique_id", "ds")][0]
            for hz in horizons:
                target_ds = origin + pd.Timedelta(hours=int(hz))
                pred_row = fcst.loc[fcst["ds"] == target_ds]
                true_row = series.loc[series["ds"] == target_ds]
                if pred_row.empty or true_row.empty:
                    continue
                collected[hz][0].append(float(true_row["y"].iloc[0]))
                collected[hz][1].append(float(pred_row[pred_col].iloc[0]))

    if n_failed:
        logger.warning(
            "Walk-forward: %s/%s origins failed to produce a forecast",
            n_failed,
            n_attempted,
        )
    else:
        logger.info("Walk-forward: %s origins produced forecasts", n_attempted)

    return {
        hz: (np.asarray(vals[0], dtype=float), np.asarray(vals[1], dtype=float))
        for hz, vals in collected.items()
    }


def rows_for_model(
    model_name: str,
    per_horizon: dict[int, tuple[np.ndarray, np.ndarray]],
    horizons: tuple[int, ...] = HORIZONS,
) -> list[dict]:
    rows = []
    for hz in horizons:
        y_true, y_pred = per_horizon.get(hz, (np.array([]), np.array([])))
        metrics = metrics_for_horizon(y_true, y_pred)
        label = HORIZON_LABELS.get(hz, f"{hz}h")
        rows.append(
            {
                "model_horizon": f"{model_name}-{label}",
                "model": model_name,
                "horizon": label,
                **metrics,
            }
        )
    return rows


def write_comparison_table(
    model_name: str,
    rows: list[dict],
    dest_dir: Path | None = None,
) -> Path:
    dest_dir = dest_dir or artifacts_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_path = dest_dir / COMPARISON_CSV
    columns = ["model_horizon", "model", "horizon", "r2", "rmse", "mape", "n", "pass"]

    if csv_path.is_file():
        existing = pd.read_csv(csv_path)
        existing = existing[existing["model"] != model_name]
        table = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    else:
        table = pd.DataFrame(rows)

    order = {name: i for i, name in enumerate(("TFT", "LSTM"))}
    hz_order = {label: i for i, label in enumerate(("6h", "24h", "7d"))}
    table["_m"] = table["model"].map(lambda m: order.get(m, 99))
    table["_h"] = table["horizon"].map(lambda h: hz_order.get(h, 99))
    table = table.sort_values(["_m", "_h"]).drop(columns=["_m", "_h"])
    table = table[[c for c in columns if c in table.columns]]
    table.to_csv(csv_path, index=False)

    md_path = dest_dir / COMPARISON_MD
    md_path.write_text(_to_markdown(table), encoding="utf-8")

    json_path = dest_dir / f"{model_name.lower()}_v1_metrics.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return csv_path


def _to_markdown(table: pd.DataFrame) -> str:
    header = (
        "# DO forecast comparison (RO2)\n\n"
        "Metrics are computed **separately per horizon** (not averaged). "
        "Targets: R² > 0.85, MAPE < 10% (Section 3.3.2.5). "
        "RMSE is reported without a pass threshold.\n\n"
    )
    cols = list(table.columns)
    lines = [
        header,
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in table.iterrows():
        cells = ["" if pd.isna(row[c]) else str(row[c]) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)
