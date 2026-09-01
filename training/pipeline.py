"""Shared NeuralForecast fit / save / evaluate loop for TFT and LSTM."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.evaluate import rolling_evaluate, rows_for_model, write_comparison_table
from training.preprocess import (
    DEFAULT_ENCODER_LENGTH,
    FREQ,
    FUTR_EXOG,
    HIST_EXOG,
    HORIZONS,
    InsufficientDataError,
    artifacts_dir,
    default_dataset_path,
    load_and_prepare,
)

logger = logging.getLogger("kja.training")

ModelFactory = Callable[..., object]


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--data",
        type=Path,
        default=default_dataset_path(),
        help="CSV path (semicolon-delimited, contract columns)",
    )
    parser.add_argument(
        "--encoder-length",
        type=int,
        default=DEFAULT_ENCODER_LENGTH,
        help="Hourly lookback (default 336 = 14 days)",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default=",".join(str(h) for h in HORIZONS),
        help="Comma-separated hourly horizons; max is the model h",
    )
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--epochs", type=int, default=None, help="Alias for --max-steps")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--step-size", type=int, default=6, help="Rolling-eval stride")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Override artifacts directory",
    )
    return parser


def parse_horizons(raw: str) -> tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise ValueError("At least one horizon is required")
    return values


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
        force=True,
    )


def run_experiment(
    *,
    model_factory: ModelFactory,
    model_name: str,
    artifact_name: str,
    data_path: Path,
    encoder_length: int,
    horizons: tuple[int, ...],
    max_steps: int,
    batch_size: int,
    step_size: int,
    dest_dir: Path | None = None,
) -> Path:
    _configure_logging()
    dest_dir = dest_dir or artifacts_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting %s training | data=%s encoder=%s horizons=%s max_steps=%s batch_size=%s",
        model_name,
        data_path,
        encoder_length,
        list(horizons),
        max_steps,
        batch_size,
    )

    try:
        train, val, test, static_names = load_and_prepare(
            data_path, encoder_length=encoder_length, horizons=horizons
        )
    except InsufficientDataError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    hist_exog = [c for c in HIST_EXOG if c in train.columns]
    futr_exog = [c for c in FUTR_EXOG if c in train.columns]
    logger.info(
        "Features: hist_exog=%s futr_exog=%s static=%s",
        hist_exog,
        futr_exog,
        static_names,
    )

    logger.info(
        "Importing neuralforecast/PyTorch (this can take a while, no output is normal)"
    )
    from neuralforecast import NeuralForecast

    logger.info("Building %s model", model_name)
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
        drop = [c for c in static_names if c in history.columns]
        history = history.drop(columns=drop)
        test = test.drop(columns=[c for c in static_names if c in test.columns])

    nf = NeuralForecast(models=[model], freq=FREQ)
    fit_kwargs = {}
    if val_size > 0:
        fit_kwargs["val_size"] = val_size
        logger.info("Validation window: %s hourly steps per series", val_size)
    if static_df is not None:
        fit_kwargs["static_df"] = static_df
    logger.info("Fitting %s on %s hourly rows (max_steps=%s)", model_name, len(history), max_steps)
    nf.fit(df=history, **fit_kwargs)
    logger.info("Fit complete")

    artifact_path = dest_dir / artifact_name
    logger.info("Saving artifact to %s", artifact_path)
    nf.save(path=str(artifact_path), overwrite=True, save_dataset=False)

    quantiles = None
    loss = getattr(model, "loss", None)
    raw_qs = getattr(loss, "quantiles", None)
    if raw_qs is not None:
        quantiles = [float(q) for q in raw_qs.detach().cpu().tolist()]
    meta = {
        "model": model_name,
        "artifact": artifact_name,
        "encoder_length": encoder_length,
        "horizon": max(horizons),
        "horizons": list(horizons),
        "hist_exog": hist_exog,
        "futr_exog": futr_exog,
        "stat_exog": static_names,
        "quantiles": quantiles,
        "freq": FREQ,
        "data": str(data_path),
    }
    meta_path = dest_dir / f"{artifact_name}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("Wrote %s", meta_path)

    logger.info("Running walk-forward evaluation (step_size=%s)", step_size)
    per_horizon = rolling_evaluate(
        nf,
        history,
        test,
        encoder_length=encoder_length,
        horizons=horizons,
        step_size=step_size,
        static_df=static_df,
        has_futr_exog=bool(futr_exog),
    )
    rows = rows_for_model(model_name, per_horizon, horizons=horizons)
    for row in rows:
        logger.info(
            "  %s  R²=%s  RMSE=%s  MAPE=%s  PICP=%s  n=%s  %s",
            row["model_horizon"],
            row["r2"],
            row["rmse"],
            row["mape"],
            row.get("picp"),
            row["n"],
            row["pass"],
        )
    csv_path = write_comparison_table(model_name, rows, dest_dir=dest_dir)
    logger.info("Wrote comparison table %s", csv_path)
    logger.info("%s training finished", model_name)
    return csv_path
