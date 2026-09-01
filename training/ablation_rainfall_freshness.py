"""Rainfall-freshness ablation: how much does DO forecast accuracy degrade
when rainfall_forecast_mm goes stale (no BMKG/VPS sync) for an extended
period?

Answers directly: fit one model normally, then evaluate it TWICE on the
same test window -- once with the dataset's real rainfall values ("fresh"),
once with rainfall frozen at its last known value for the final
--outage-days of the test window ("frozen"). Only rainfall is frozen; DO,
pH, temperature, salinity, turbidity, and light stay real, because those
arrive over LoRa and do not depend on internet at all (see
api/sensors.py's "No live rainfall_forecast_mm source by design" note --
this script quantifies the cost of that design choice).

NOT runnable yet: `dataset_madong.csv` is a short synthetic file for code
verification, not a source of real findings. Run this once real field data
is available (from Nov 2026 onward).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.evaluate import rolling_evaluate, rows_for_model
from training.pipeline import parse_horizons
from training.preprocess import (
    DEFAULT_ENCODER_LENGTH,
    FREQ,
    FUTR_EXOG,
    HIST_EXOG,
    HORIZONS,
    artifacts_dir,
    default_dataset_path,
    load_and_prepare,
)
from training.train_lstm import _build_lstm
from training.train_tft import _build_tft

MODEL_FACTORIES = {"tft": (_build_tft, "TFT"), "lstm": (_build_lstm, "LSTM")}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare forecast accuracy with fresh vs. stale rainfall_forecast_mm"
    )
    parser.add_argument("--data", type=Path, default=default_dataset_path())
    parser.add_argument("--encoder-length", type=int, default=DEFAULT_ENCODER_LENGTH)
    parser.add_argument("--horizons", type=str, default=",".join(str(h) for h in HORIZONS))
    parser.add_argument("--model", choices=list(MODEL_FACTORIES), default="tft")
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--step-size", type=int, default=6)
    parser.add_argument(
        "--outage-days",
        type=int,
        default=30,
        help="Simulated no-internet duration at the END of the test window",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser


def _freeze_value_before(full: pd.DataFrame, uid: str, outage_start: pd.Timestamp) -> float:
    """Last known rainfall_forecast_mm for `uid` strictly before outage_start.

    Looked up from the full (history + test) series, not just the test
    slice, so a short test window doesn't wrongly fall back to 0.0.
    """
    before = full.loc[
        (full["unique_id"] == uid) & (full["ds"] < outage_start),
        "rainfall_forecast_mm",
    ].dropna()
    return float(before.iloc[-1]) if not before.empty else 0.0


def freeze_rainfall(
    test: pd.DataFrame,
    full: pd.DataFrame,
    outage_start: pd.Timestamp,
) -> pd.DataFrame:
    """Copy of `test` with rainfall_forecast_mm held constant from outage_start on.

    Simulates a Pi that stopped syncing from the VPS at outage_start: every
    row from that point gets whatever value was last known just before the
    outage began, instead of the dataset's (unrealistically perfect,
    ex-post-actual) values.
    """
    if "rainfall_forecast_mm" not in test.columns:
        return test.copy()
    out = test.copy()
    for uid in out["unique_id"].unique():
        freeze_value = _freeze_value_before(full, uid, outage_start)
        mask = (out["unique_id"] == uid) & (out["ds"] >= outage_start)
        out.loc[mask, "rainfall_forecast_mm"] = freeze_value
    return out


def _to_markdown(table: pd.DataFrame) -> str:
    header = (
        "# Rainfall-freshness ablation\n\n"
        "Same fitted model, evaluated twice on the same test window: once "
        "with real rainfall_forecast_mm ('fresh'), once with it frozen at "
        "the last known value for the final N days ('frozen'). Only "
        "rainfall is frozen -- DO and the other sensors stay real, since "
        "they arrive over LoRa independent of internet connectivity. "
        "Answers: how much does a prolonged Pi/BMKG sync outage cost in "
        "forecast accuracy, per horizon?\n\n"
    )
    cols = [c for c in table.columns if c != "model_horizon"]
    lines = [
        header,
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in table.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def run_ablation(
    *,
    data_path: Path,
    encoder_length: int,
    horizons: tuple[int, ...],
    model_key: str,
    max_steps: int,
    batch_size: int,
    step_size: int,
    outage_days: int,
    out_dir: Path | None = None,
) -> Path:
    model_factory, model_name = MODEL_FACTORIES[model_key]
    out_dir = out_dir or (artifacts_dir() / "ablation_rainfall" / model_key)
    out_dir.mkdir(parents=True, exist_ok=True)

    train, val, test, static_names = load_and_prepare(
        data_path, encoder_length=encoder_length, horizons=horizons
    )
    hist_exog = [c for c in HIST_EXOG if c in train.columns]
    futr_exog = [c for c in FUTR_EXOG if c in train.columns]
    if not futr_exog:
        raise ValueError("Dataset has no rainfall_forecast_mm column -- nothing to freeze.")

    from neuralforecast import NeuralForecast

    model = model_factory(
        h=max(horizons),
        input_size=encoder_length,
        hist_exog_list=hist_exog,
        futr_exog_list=futr_exog,
        stat_exog_list=list(static_names) if static_names else None,
        max_steps=max_steps,
        batch_size=batch_size,
    )

    history = (
        pd.concat([train, val], ignore_index=True)
        .sort_values(["unique_id", "ds"])
        .reset_index(drop=True)
    )
    test = test.sort_values(["unique_id", "ds"]).reset_index(drop=True)
    val_size = int(val.groupby("unique_id").size().min()) if len(val) else 0
    static_df = None
    if static_names:
        static_df = history[["unique_id", *static_names]].drop_duplicates("unique_id")
        history = history.drop(columns=static_names)
        test = test.drop(columns=[c for c in static_names if c in test.columns])

    nf = NeuralForecast(models=[model], freq=FREQ)
    fit_kwargs: dict = {}
    if val_size > 0:
        fit_kwargs["val_size"] = val_size
    if static_df is not None:
        fit_kwargs["static_df"] = static_df
    nf.fit(df=history, **fit_kwargs)

    eval_kwargs = dict(
        encoder_length=encoder_length,
        horizons=horizons,
        step_size=step_size,
        static_df=static_df,
        has_futr_exog=True,
    )

    fresh = rolling_evaluate(nf, history, test, **eval_kwargs)
    rows = rows_for_model(f"{model_name}-fresh", fresh, horizons=horizons)

    full = pd.concat([history, test], ignore_index=True).sort_values(["unique_id", "ds"])
    outage_start = test["ds"].max() - pd.Timedelta(days=outage_days)
    test_frozen = freeze_rainfall(test, full, outage_start)
    frozen = rolling_evaluate(nf, history, test_frozen, **eval_kwargs)
    rows += rows_for_model(f"{model_name}-frozen{outage_days}d", frozen, horizons=horizons)

    table = pd.DataFrame(rows)
    hz_order = {"6h": 0, "24h": 1, "7d": 2}
    table["_h"] = table["horizon"].map(lambda h: hz_order.get(h, 99))
    table = table.sort_values(["_h", "model"]).drop(columns=["_h"])

    csv_path = out_dir / "rainfall_freshness_ablation.csv"
    table.to_csv(csv_path, index=False)
    (out_dir / "rainfall_freshness_ablation.md").write_text(_to_markdown(table), encoding="utf-8")
    return csv_path


def main() -> None:
    args = build_arg_parser().parse_args()
    csv_path = run_ablation(
        data_path=args.data,
        encoder_length=args.encoder_length,
        horizons=parse_horizons(args.horizons),
        model_key=args.model,
        max_steps=args.max_steps,
        batch_size=args.batch_size,
        step_size=args.step_size,
        outage_days=args.outage_days,
        out_dir=args.out_dir,
    )
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
