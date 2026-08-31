"""Train a lightweight LSTM baseline for empirical TFT comparison (RO2)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.pipeline import build_arg_parser, parse_horizons, run_experiment


def _build_lstm(
    *,
    h: int,
    input_size: int,
    hist_exog_list: list[str],
    futr_exog_list: list[str],
    stat_exog_list: list[str] | None,
    max_steps: int,
    batch_size: int,
):
    from neuralforecast.losses.pytorch import MAE
    from neuralforecast.models import LSTM

    return LSTM(
        h=h,
        input_size=input_size,
        hist_exog_list=hist_exog_list,
        futr_exog_list=futr_exog_list or [],
        stat_exog_list=stat_exog_list or [],
        encoder_n_layers=1,
        encoder_hidden_size=64,
        encoder_dropout=0.1,
        decoder_layers=1,
        decoder_hidden_size=64,
        loss=MAE(),
        max_steps=max_steps,
        batch_size=batch_size,
        scaler_type="robust",
        early_stop_patience_steps=5,
        alias="LSTM",
        accelerator="cpu",
        enable_checkpointing=False,
    )


def main() -> None:
    parser = build_arg_parser(
        "Train LSTM baseline for DO forecast (+6h, +24h, +7d)"
    )
    args = parser.parse_args()
    max_steps = args.epochs if args.epochs is not None else args.max_steps
    run_experiment(
        model_factory=_build_lstm,
        model_name="LSTM",
        artifact_name="lstm_baseline_v1",
        data_path=args.data,
        encoder_length=args.encoder_length,
        horizons=parse_horizons(args.horizons),
        max_steps=max_steps,
        batch_size=args.batch_size,
        step_size=args.step_size,
        dest_dir=args.artifacts_dir,
    )


if __name__ == "__main__":
    main()
