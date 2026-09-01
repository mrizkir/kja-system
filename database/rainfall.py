"""Lookup cached VPS rainfall by timestamp (at-or-before)."""

from __future__ import annotations

from datetime import datetime, timedelta

from database.models import RainfallForecast

FUTURE_HORIZON_HOURS = 168


def _naive(ts: datetime) -> datetime:
    if ts.tzinfo is not None:
        return ts.replace(tzinfo=None)
    return ts


def _walk_at_or_before(
    rows: list[RainfallForecast],
    timestamps: list[datetime],
) -> list[float | None]:
    """One value per input timestamp, in the SAME order given.

    The single forward-only pointer requires ascending timestamps, so this
    sorts internally (with original positions) rather than trusting callers
    to already be sorted -- an unsorted input silently produced wrong
    "at-or-before" values with no error before this fix.
    """
    n = len(rows)
    order = sorted(range(len(timestamps)), key=lambda i: _naive(timestamps[i]))
    values: list[float | None] = [None] * len(timestamps)
    j = -1
    for i in order:
        target = _naive(timestamps[i])
        while j + 1 < n and rows[j + 1].target_timestamp <= target:
            j += 1
        values[i] = None if j < 0 else float(rows[j].rainfall_forecast_mm)
    return values


def load_ordered(session) -> list[RainfallForecast]:
    return (
        session.query(RainfallForecast)
        .order_by(RainfallForecast.target_timestamp.asc())
        .all()
    )


def backfill_history(session, readings: list[dict]) -> list[dict]:
    if not readings:
        return readings
    rows = load_ordered(session)
    stamps: list[datetime] = []
    for item in readings:
        ts = item.get("timestamp")
        if isinstance(ts, datetime):
            stamps.append(_naive(ts))
        else:
            stamps.append(_naive(datetime.fromisoformat(str(ts).replace("Z", "+00:00"))))
    rains = _walk_at_or_before(rows, stamps)
    out: list[dict] = []
    for item, rain in zip(readings, rains):
        filled = dict(item)
        if rain is not None:
            filled["rainfall_forecast_mm"] = rain
        out.append(filled)
    return out


def future_rainfall_mm(
    session,
    origin: datetime,
    horizon_hours: int = FUTURE_HORIZON_HOURS,
) -> list[dict]:
    origin = _naive(origin)
    stamps = [origin + timedelta(hours=i) for i in range(1, horizon_hours + 1)]
    rows = load_ordered(session)
    rains = _walk_at_or_before(rows, stamps)
    result: list[dict] = []
    for ts, rain in zip(stamps, rains):
        if rain is None:
            continue
        result.append(
            {
                "timestamp": ts.isoformat(sep=" "),
                "rainfall_forecast_mm": rain,
            }
        )
    return result


def last_fetched_at(session) -> datetime | None:
    row = (
        session.query(RainfallForecast)
        .order_by(RainfallForecast.fetched_at.desc())
        .first()
    )
    return None if row is None else row.fetched_at


def row_count(session) -> int:
    return session.query(RainfallForecast).count()
