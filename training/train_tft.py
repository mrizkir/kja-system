"""Train Temporal Fusion Transformer for multi-horizon DO forecasting."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.pipeline import build_arg_parser, parse_horizons, run_experiment


def _build_tft(
    *,
    h: int,
    input_size: int,
    hist_exog_list: list[str],
    futr_exog_list: list[str],
    stat_exog_list: list[str] | None,
    max_steps: int,
    batch_size: int,
):
    from neuralforecast.losses.pytorch import MQLoss
    from neuralforecast.models import TFT

    return TFT(
        h=h,
        input_size=input_size,
        hist_exog_list=hist_exog_list,
        futr_exog_list=futr_exog_list or [],
        stat_exog_list=stat_exog_list or [],
        # Lim et al. 2021: Q10 / Q50 / Q90 (80% prediction interval around the median).
        loss=MQLoss(quantiles=[0.1, 0.5, 0.9]),
        max_steps=max_steps,
        batch_size=batch_size,
        scaler_type="robust",
        start_padding_enabled=True,
        early_stop_patience_steps=5,
        # Reduced-capacity config for the pilot data scale (~2,928 hourly
        # points): library defaults (n_head=4, hidden_size=128) overfit a
        # dataset this small. Matches the capacity described in Chapter 3
        # for the TFT-vs-LSTM comparison (Jawaban 6) -- keep in sync if
        # either changes.
        n_head=1,
        hidden_size=64,
        dropout=0.2,
        alias="TFT",
        accelerator="cpu",
        enable_checkpointing=False,
    )


def main() -> None:
    parser = build_arg_parser("Train TFT for DO forecast (+6h, +24h, +7d)")
    args = parser.parse_args()
    max_steps = args.epochs if args.epochs is not None else args.max_steps
    run_experiment(
        model_factory=_build_tft,
        model_name="TFT",
        artifact_name="tft_v1",
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
