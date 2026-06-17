"""Seed simulated sensor data for KJA digital twin demo."""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models import (
    Alert,
    AlertSeverity,
    Base,
    DoSource,
    KjaUnit,
    SensorReading,
    Species,
    get_engine,
    get_session,
)

THRESHOLDS = {
    "ph": {"normal": (7.5, 8.5), "warn_low": 7.3, "warn_high": 8.7, "danger_low": 7.0, "danger_high": 9.0},
    "temperature": {"normal": (26, 30), "warn_low": 24, "warn_high": 31, "danger_low": 22, "danger_high": 33},
    "salinity": {"normal": (28, 34), "warn_low": 24, "warn_high": 34, "danger_low": 22},
    "turbidity": {"normal_max": 15, "warn_max": 30},
    "do_predicted": {"normal_min": 5.0, "warn_min": 4.0},
}


def evaluate_parameter(parameter: str, value: float) -> AlertSeverity | None:
    if parameter == "ph":
        if value < THRESHOLDS["ph"]["danger_low"] or value > THRESHOLDS["ph"]["danger_high"]:
            return AlertSeverity.danger
        if value < THRESHOLDS["ph"]["warn_low"] or value > THRESHOLDS["ph"]["warn_high"]:
            return AlertSeverity.warn
        return None

    if parameter == "temperature":
        if value < THRESHOLDS["temperature"]["danger_low"] or value > THRESHOLDS["temperature"]["danger_high"]:
            return AlertSeverity.danger
        if value < THRESHOLDS["temperature"]["warn_low"] or value > THRESHOLDS["temperature"]["warn_high"]:
            return AlertSeverity.warn
        return None

    if parameter == "salinity":
        if value < THRESHOLDS["salinity"]["danger_low"]:
            return AlertSeverity.danger
        low, high = THRESHOLDS["salinity"]["normal"]
        if value < low or value > high:
            return AlertSeverity.warn
        return None

    if parameter == "turbidity":
        if value > THRESHOLDS["turbidity"]["warn_max"]:
            return AlertSeverity.danger
        if value > THRESHOLDS["turbidity"]["normal_max"]:
            return AlertSeverity.warn
        return None

    if parameter == "do_predicted":
        if value < THRESHOLDS["do_predicted"]["warn_min"]:
            return AlertSeverity.danger
        if value < THRESHOLDS["do_predicted"]["normal_min"]:
            return AlertSeverity.warn
        return None

    return None


def _generate_reading(kja_name: str, hour_index: int, total_hours: int) -> dict:
    """Generate one hourly reading with scenario-specific patterns."""
    rng = random.Random(f"{kja_name}-{hour_index}")

    # Monsoon: slightly low salinity across all units
    salinity = round(rng.uniform(24.0, 27.5), 2)

    ph = round(rng.uniform(7.6, 8.4), 2)
    temperature = round(rng.uniform(26.5, 29.5), 2)
    turbidity = round(rng.uniform(8.0, 14.0), 2)
    light_intensity = round(rng.uniform(12000, 45000), 0)

    # KJA-03: declining DO trend (danger scenario)
    if kja_name == "KJA-03":
        progress = hour_index / max(total_hours - 1, 1)
        do_predicted = round(6.8 - (progress * 3.2) + rng.uniform(-0.15, 0.15), 2)
        if hour_index >= total_hours - 6:
            turbidity = round(rng.uniform(18.0, 32.0), 2)
    else:
        do_predicted = round(rng.uniform(5.2, 7.5), 2)

    return {
        "ph": ph,
        "temperature": temperature,
        "salinity": salinity,
        "turbidity": turbidity,
        "light_intensity": light_intensity,
        "do_predicted": do_predicted,
        "do_source": DoSource.tft,
    }


def _alert_message(kja_name: str, parameter: str, value: float, severity: AlertSeverity) -> str:
    labels = {
        "ph": "pH",
        "temperature": "Suhu",
        "salinity": "Salinitas",
        "turbidity": "Turbiditas",
        "do_predicted": "DO (prediksi)",
    }
    label = labels.get(parameter, parameter)
    level = {"info": "Info", "warn": "Perhatian", "danger": "Kritis"}[severity.value]
    return f"[{level}] {kja_name}: {label} = {value}"


def seed_database() -> None:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = get_session()

    units = [
        KjaUnit(name="KJA-01", species=Species.grouper, status="active", farmer_name="Bapak Ahmad"),
        KjaUnit(name="KJA-02", species=Species.snapper, status="active", farmer_name="Ibu Siti"),
        KjaUnit(name="KJA-03", species=Species.grouper, status="warning", farmer_name="Bapak Rizki"),
        KjaUnit(name="KJA-04", species=Species.snapper, status="active", farmer_name="Bapak Dani"),
    ]
    session.add_all(units)
    session.flush()

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    total_hours = 168  # 7 days

    for unit in units:
        for hour_index in range(total_hours):
            ts = now - timedelta(hours=total_hours - 1 - hour_index)
            data = _generate_reading(unit.name, hour_index, total_hours)
            session.add(
                SensorReading(
                    kja_id=unit.id,
                    timestamp=ts,
                    **data,
                )
            )

    session.flush()

    # Generate alerts from the most recent readings
    for unit in units:
        latest = (
            session.query(SensorReading)
            .filter(SensorReading.kja_id == unit.id)
            .order_by(SensorReading.timestamp.desc())
            .first()
        )
        if not latest:
            continue

        checks = {
            "ph": latest.ph,
            "temperature": latest.temperature,
            "salinity": latest.salinity,
            "turbidity": latest.turbidity,
            "do_predicted": latest.do_predicted,
        }

        for parameter, value in checks.items():
            severity = evaluate_parameter(parameter, value)
            if severity:
                session.add(
                    Alert(
                        kja_id=unit.id,
                        parameter=parameter,
                        severity=severity,
                        message=_alert_message(unit.name, parameter, value, severity),
                        timestamp=latest.timestamp,
                        is_read=False,
                    )
                )

    session.commit()
    session.close()
    print("Database seeded: 4 KJA units, 168 readings each, alerts generated.")


if __name__ == "__main__":
    seed_database()
