"""Encoder-length ablation for empirical justification (Chapter 4).

Replaces an unverified "encoder >= 2x horizon" heuristic: candidate
window sizes are trained and scored on the validation/test split, and
the results are collected into one table per horizon so the choice of
encoder_length can be argued from evidence rather than a rule of thumb.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.evaluate import COMPARISON_CSV
from training.pipeline import parse_horizons, run_experiment
from training.preprocess import HORIZONS, artifacts_dir, default_dataset_path, ABLATION_ENCODER_LENGTHS
from training.train_lstm import _build_lstm
from training.train_tft import _build_tft

MODEL_FACTORIES = {"tft": (_build_tft, "TFT"), "lstm": (_build_lstm, "LSTM")}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ablate encoder_length and collect per-horizon metrics"
    )
    parser.add_argument("--data", type=Path, default=default_dataset_path())
    parser.add_argument(
        "--encoder-lengths",
        type=str,
        default=",".join(str(v) for v in ABLATION_ENCODER_LENGTHS),
        help="Comma-separated hourly window sizes (default: 7d,14d,21d)",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default=",".join(str(h) for h in HORIZONS),
    )
    parser.add_argument("--model", choices=list(MODEL_FACTORIES), default="tft")
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--step-size", type=int, default=6)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Where per-length runs + the combined table are written",
    )
    return parser


def parse_encoder_lengths(raw: str) -> list[int]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if not values:
        raise ValueError("At least one encoder length is required")
    return values


def run_ablation(
    *,
    data_path: Path,
    encoder_lengths: list[int],
    horizons: tuple[int, ...],
    model_key: str,
    max_steps: int,
    batch_size: int,
    step_size: int,
    out_dir: Path | None = None,
) -> Path:
    model_factory, model_name = MODEL_FACTORIES[model_key]
    out_dir = out_dir or (artifacts_dir() / "ablation" / model_key)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[pd.DataFrame] = []
    for encoder_length in encoder_lengths:
        run_dir = out_dir / f"encoder_{encoder_length}"
        run_experiment(
            model_factory=model_factory,
            model_name=model_name,
            artifact_name=f"{model_key}_encoder_{encoder_length}",
            data_path=data_path,
            encoder_length=encoder_length,
            horizons=horizons,
            max_steps=max_steps,
            batch_size=batch_size,
            step_size=step_size,
            dest_dir=run_dir,
        )
        table = pd.read_csv(run_dir / COMPARISON_CSV)
        table.insert(0, "encoder_length", encoder_length)
        rows.append(table)

    combined = pd.concat(rows, ignore_index=True)
    hz_order = {"6h": 0, "24h": 1, "7d": 2}
    combined["_h"] = combined["horizon"].map(lambda h: hz_order.get(h, 99))
    combined = combined.sort_values(["_h", "encoder_length"]).drop(columns=["_h"])

    csv_path = out_dir / "encoder_length_ablation.csv"
    combined.to_csv(csv_path, index=False)
    (out_dir / "encoder_length_ablation.md").write_text(
        _to_markdown(combined), encoding="utf-8"
    )
    return csv_path


def _to_markdown(table: pd.DataFrame) -> str:
    header = (
        "# Encoder-length ablation\n\n"
        "Candidate lookback windows evaluated per horizon (not averaged), "
        "used to select encoder_length empirically instead of a fixed "
        "literature rule. R² / MAPE use Q50; PICP (Q10–Q90 coverage) is "
        "diagnostic only. Targets: R² > 0.85, MAPE < 10% (Section 3.3.2.5).\n\n"
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


def main() -> None:
    args = build_arg_parser().parse_args()
    csv_path = run_ablation(
        data_path=args.data,
        encoder_lengths=parse_encoder_lengths(args.encoder_lengths),
        horizons=parse_horizons(args.horizons),
        model_key=args.model,
        max_steps=args.max_steps,
        batch_size=args.batch_size,
        step_size=args.step_size,
        out_dir=args.out_dir,
    )
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
