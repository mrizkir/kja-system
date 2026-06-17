"""TFT model inference module (stub)."""

from __future__ import annotations

import time


def predict_do(kja_id: int, last_24h_readings: list[dict]) -> dict:
    """
    Predict dissolved oxygen levels using TFT model.

    Args:
        kja_id: KJA unit identifier.
        last_24h_readings: List of dicts with sensor readings from last 24 hours.

    Returns:
        Dict with do_now, do_2h, do_4h, do_6h, confidence, latency_ms.
    """
    # TODO: Replace with neuralforecast TFT model
    start = time.perf_counter()

    if last_24h_readings:
        recent_do = [r.get("do_predicted", 5.0) for r in last_24h_readings[-6:]]
        do_now = sum(recent_do) / len(recent_do)
    else:
        do_now = 5.5

    # KJA-03 demo: declining forecast
    if kja_id == 3:
        do_now = min(do_now, 3.8)
        do_2h = round(do_now - 0.3, 2)
        do_4h = round(do_now - 0.7, 2)
        do_6h = round(do_now - 1.1, 2)
        confidence = 0.87
    else:
        do_2h = round(do_now + 0.1, 2)
        do_4h = round(do_now + 0.05, 2)
        do_6h = round(do_now - 0.05, 2)
        confidence = 0.92

    latency_ms = round((time.perf_counter() - start) * 1000 + 45, 1)

    return {
        "do_now": round(do_now, 2),
        "do_2h": do_2h,
        "do_4h": do_4h,
        "do_6h": do_6h,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }
