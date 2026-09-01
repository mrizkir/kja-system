"""Pick Lightning accelerator from the machine that is running now."""

from __future__ import annotations

import logging

logger = logging.getLogger("kja.training")


def lightning_accelerator() -> str:
    """``gpu`` if CUDA is present, otherwise ``cpu`` (laptop / Pi / MPS-only Mac)."""
    import torch

    return "gpu" if torch.cuda.is_available() else "cpu"


def apply_runtime_accelerator(nf) -> str:
    """Override saved Trainer kwargs so a GPU artifact can run on CPU (and vice versa)."""
    accel = lightning_accelerator()
    models = list(getattr(nf, "models", []) or [])
    models.extend(getattr(nf, "models_init", []) or [])
    seen: set[int] = set()
    for model in models:
        mid = id(model)
        if mid in seen:
            continue
        seen.add(mid)
        kwargs = getattr(model, "trainer_kwargs", None)
        if not isinstance(kwargs, dict):
            continue
        kwargs["accelerator"] = accel
        if accel == "cpu":
            kwargs.pop("devices", None)
        else:
            kwargs.setdefault("devices", -1)
    logger.info("NeuralForecast trainer accelerator=%s", accel)
    return accel
