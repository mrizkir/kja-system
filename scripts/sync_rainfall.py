"""Pull rainfall forecasts from the VPS cache when the Pi has connectivity.

Failed attempts (no internet, DNS, timeout, bad payload) are the normal
case and must not page anyone. Cron should call this every
RAINFALL_SYNC_INTERVAL_SECONDS (see README.md in this directory).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config
from database.models import Base, RainfallForecast, get_engine, get_session

logger = logging.getLogger("kja.rainfall_sync")


def _naive_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            return None
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return ts.replace(minute=0, second=0, microsecond=0)


def _parse_rows(payload: object) -> list[tuple[datetime, float]]:
    # ADAPT: confirm this matches the real VPS response shape
    if not isinstance(payload, list):
        raise ValueError("expected a JSON array")
    parsed: list[tuple[datetime, float]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ts = _naive_timestamp(item.get("timestamp"))
        raw = item.get("rainfall_forecast_mm")
        if ts is None or raw is None:
            continue
        parsed.append((ts, float(raw)))
    return parsed


def _upsert(session, rows: list[tuple[datetime, float]], fetched_at: datetime) -> int:
    by_ts = {ts: mm for ts, mm in rows}
    existing = (
        session.query(RainfallForecast)
        .filter(RainfallForecast.target_timestamp.in_(list(by_ts)))
        .all()
        if by_ts
        else []
    )
    found = {row.target_timestamp: row for row in existing}
    n = 0
    for ts, mm in by_ts.items():
        row = found.get(ts)
        if row is None:
            session.add(
                RainfallForecast(
                    target_timestamp=ts,
                    rainfall_forecast_mm=mm,
                    fetched_at=fetched_at,
                )
            )
        else:
            row.rainfall_forecast_mm = mm
            row.fetched_at = fetched_at
        n += 1
    session.commit()
    return n


def sync_rainfall() -> int:
    """One GET + upsert. Returns rows written, or 0 on skip/failure."""
    url = (Config.VPS_RAINFALL_URL or "").strip()
    if not url:
        logger.info("no connectivity: VPS_RAINFALL_URL is not set")
        print("rainfall sync: skipped (VPS_RAINFALL_URL unset)")
        return 0

    try:
        Base.metadata.create_all(get_engine())
    except Exception as exc:
        logger.info("no connectivity: %s", exc)
        print(f"rainfall sync: no connectivity ({exc.__class__.__name__})")
        return 0
    timeout = Config.RAINFALL_SYNC_TIMEOUT_SECONDS
    headers = {"Accept": "application/json"}
    key = (Config.VPS_RAINFALL_API_KEY or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = getattr(response, "status", 200)
        if status >= 400:
            logger.info("no connectivity: HTTP %s from VPS rainfall endpoint", status)
            print(f"rainfall sync: no connectivity (HTTP {status})")
            return 0
        payload = json.loads(raw.decode("utf-8"))
        rows = _parse_rows(payload)
    except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.info("no connectivity: %s", exc)
        print(f"rainfall sync: no connectivity ({exc.__class__.__name__})")
        return 0

    session = get_session()
    try:
        n = _upsert(session, rows, datetime.utcnow())
    except Exception as exc:
        session.rollback()
        logger.info("no connectivity: upsert failed (%s)", exc)
        print(f"rainfall sync: no connectivity ({exc.__class__.__name__})")
        return 0
    finally:
        session.close()

    logger.info("synced %s rainfall rows from VPS", n)
    print(f"rainfall sync: synced {n} rows")
    return n


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    try:
        sync_rainfall()
    except Exception as exc:
        logger.info("no connectivity: %s", exc)
        print(f"rainfall sync: no connectivity ({exc.__class__.__name__})")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
