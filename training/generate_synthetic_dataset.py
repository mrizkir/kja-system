"""Generate a synthetic dataset_madong.csv long enough for the pipeline.

Duration is derived from `preprocess.min_series_hours`, not a guessed
number, so it stays correct if encoder-length candidates change. Rows
are synthesized directly at hourly granularity (not the 5-second raw
cadence used in the small practice sample) because the pipeline
resamples everything to hourly before it reaches any model, and 50
days at 5-second resolution would be ~864,000 rows for no benefit.

This dataset exists to exercise the pipeline end-to-end for code
verification. It is NOT a substitute for real KJA sensor history in
the dissertation's final results.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.preprocess import ABLATION_ENCODER_LENGTHS, HORIZONS, min_series_hours

MARGIN = 1.25


def default_hours() -> int:
    needed = min_series_hours(max(ABLATION_ENCODER_LENGTHS), max(HORIZONS))
    return math.ceil(needed * MARGIN / 24) * 24


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


def generate_rows(kja_id: int, hours: int, start: datetime, seed: int) -> list[str]:
    rng = random.Random(seed)

    rain_day = False
    rain_intensity = 0.0
    salinity_drift = 0.0
    ph_drift = 0.0
    temp_drift = 0.0
    turbidity_carry = 0.0

    rows = []
    for h in range(hours):
        ts = start + timedelta(hours=h)
        hour_of_day = ts.hour
        day_index = h // 24

        # Rain events decided once per day, held for ~6-12 evening hours.
        if hour_of_day == 0:
            rain_day = rng.random() < 0.22
            rain_intensity = rng.uniform(2.0, 9.0) if rain_day else 0.0
        is_rain_hour = rain_day and 13 <= hour_of_day <= 21
        rainfall_forecast_mm = round(rain_intensity if is_rain_hour else 0.0, 2)

        # Diurnal light: 0 at night, peak near midday.
        light_shape = max(0.0, math.sin(math.pi * (hour_of_day - 6) / 12))
        light_intensity = round(light_shape * rng.uniform(30000, 45000), 0)

        # Slow multi-day drifts (bounded random walk) plus diurnal component.
        temp_drift += rng.uniform(-0.05, 0.05)
        temp_drift = _clamp(temp_drift, -1.0, 1.0)
        temperature = _clamp(
            27.8 + temp_drift + 1.0 * math.sin(math.pi * (hour_of_day - 9) / 12),
            26.0,
            30.0,
        )

        ph_drift += rng.uniform(-0.01, 0.01)
        ph_drift = _clamp(ph_drift, -0.3, 0.3)
        ph = _clamp(
            8.0 + ph_drift + 0.15 * light_shape + rng.uniform(-0.02, 0.02),
            7.5,
            8.5,
        )

        salinity_drift += rng.uniform(-0.05, 0.05) - (0.3 if is_rain_hour else 0.0)
        salinity_drift = _clamp(salinity_drift, -4.0, 1.0)
        salinity = _clamp(30.5 + salinity_drift + rng.uniform(-0.1, 0.1), 26.0, 34.0)

        turbidity_carry = max(0.0, turbidity_carry * 0.85 + (4.0 if is_rain_hour else 0.0))
        turbidity = _clamp(9.0 + turbidity_carry + rng.uniform(-0.5, 0.5), 5.0, 30.0)

        weekly_cycle = 0.3 * math.sin(2 * math.pi * h / (24 * 7))
        do_diurnal = 0.6 * math.sin(math.pi * (hour_of_day - 8) / 12)
        do_rain_penalty = 0.4 * (turbidity_carry / 4.0) if turbidity_carry > 0 else 0.0
        do_observed = _clamp(
            6.2 + do_diurnal + weekly_cycle - do_rain_penalty + rng.uniform(-0.08, 0.08),
            4.2,
            7.6,
        )

        rows.append(
            f"{kja_id};{ts.strftime('%Y-%m-%d %H:%M:%S')};{ph:.2f};{temperature:.2f};"
            f"{salinity:.2f};{turbidity:.2f};{light_intensity:.0f};{do_observed:.2f};"
            f"{rainfall_forecast_mm:.2f}"
        )
        _ = day_index  # kept for readability of the per-day rain roll above

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "dataset_madong.csv")
    parser.add_argument("--kja-id", type=int, default=1)
    parser.add_argument("--hours", type=int, default=None, help="Override auto-computed duration")
    parser.add_argument("--start", type=str, default="2026-06-01 00:00:00")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    hours = args.hours or default_hours()
    start = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    rows = generate_rows(args.kja_id, hours, start, args.seed)

    header = "kja_id;timestamp;ph;temperature;salinity;turbidity;light_intensity;do_observed;rainfall_forecast_mm"
    args.output.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} hourly rows ({hours / 24:.1f} days) to {args.output}")


if __name__ == "__main__":
    main()
