from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from database.models import AlertSeverity, KjaUnit, SensorReading, get_session
from database.seed import evaluate_parameter
from inference.tft_model import predict_do

sensors_bp = Blueprint("sensors", __name__, url_prefix="/api")


def _reading_to_dict(reading: SensorReading, kja_name: str | None = None) -> dict:
    data = {
        "id": reading.id,
        "kja_id": reading.kja_id,
        "kja_name": kja_name,
        "timestamp": reading.timestamp.isoformat(),
        "ph": reading.ph,
        "temperature": reading.temperature,
        "salinity": reading.salinity,
        "turbidity": reading.turbidity,
        "light_intensity": reading.light_intensity,
        "do_predicted": reading.do_predicted,
        "do_source": reading.do_source.value,
        "status": {
            "ph": _status_label(evaluate_parameter("ph", reading.ph)),
            "temperature": _status_label(evaluate_parameter("temperature", reading.temperature)),
            "salinity": _status_label(evaluate_parameter("salinity", reading.salinity)),
            "turbidity": _status_label(evaluate_parameter("turbidity", reading.turbidity)),
            "do_predicted": _status_label(evaluate_parameter("do_predicted", reading.do_predicted)),
            "light_intensity": "normal",
        },
    }
    return data


def _status_label(severity: AlertSeverity | None) -> str:
    if severity == AlertSeverity.danger:
        return "kritis"
    if severity == AlertSeverity.warn:
        return "perhatian"
    return "normal"


@sensors_bp.route("/sensor/latest", methods=["GET"])
def latest_readings():
    session = get_session()
    try:
        subq = (
            session.query(
                SensorReading.kja_id,
                func.max(SensorReading.timestamp).label("max_ts"),
            )
            .group_by(SensorReading.kja_id)
            .subquery()
        )

        readings = (
            session.query(SensorReading, KjaUnit.name)
            .join(KjaUnit, SensorReading.kja_id == KjaUnit.id)
            .join(
                subq,
                (SensorReading.kja_id == subq.c.kja_id)
                & (SensorReading.timestamp == subq.c.max_ts),
            )
            .all()
        )

        return jsonify([_reading_to_dict(r, name) for r, name in readings])
    finally:
        session.close()


@sensors_bp.route("/sensor/history/<int:kja_id>", methods=["GET"])
def sensor_history(kja_id: int):
    hours = request.args.get("hours", default=24, type=int)
    hours = max(1, min(hours, 168))
    since = datetime.utcnow() - timedelta(hours=hours)

    session = get_session()
    try:
        unit = session.query(KjaUnit).filter(KjaUnit.id == kja_id).first()
        if not unit:
            return jsonify({"error": "KJA unit not found"}), 404

        readings = (
            session.query(SensorReading)
            .filter(SensorReading.kja_id == kja_id, SensorReading.timestamp >= since)
            .order_by(SensorReading.timestamp.asc())
            .all()
        )

        return jsonify(
            {
                "kja_id": kja_id,
                "kja_name": unit.name,
                "hours": hours,
                "readings": [_reading_to_dict(r, unit.name) for r in readings],
            }
        )
    finally:
        session.close()


@sensors_bp.route("/kja/units", methods=["GET"])
def kja_units():
    session = get_session()
    try:
        units = session.query(KjaUnit).order_by(KjaUnit.id).all()
        result = []
        for unit in units:
            latest = (
                session.query(SensorReading)
                .filter(SensorReading.kja_id == unit.id)
                .order_by(SensorReading.timestamp.desc())
                .first()
            )
            result.append(
                {
                    "id": unit.id,
                    "name": unit.name,
                    "species": unit.species.value,
                    "status": unit.status,
                    "farmer_name": unit.farmer_name,
                    "latest_reading": _reading_to_dict(latest, unit.name) if latest else None,
                }
            )
        return jsonify(result)
    finally:
        session.close()


@sensors_bp.route("/inference/do/<int:kja_id>", methods=["GET"])
def inference_do(kja_id: int):
    session = get_session()
    try:
        unit = session.query(KjaUnit).filter(KjaUnit.id == kja_id).first()
        if not unit:
            return jsonify({"error": "KJA unit not found"}), 404

        since = datetime.utcnow() - timedelta(hours=24)
        readings = (
            session.query(SensorReading)
            .filter(SensorReading.kja_id == kja_id, SensorReading.timestamp >= since)
            .order_by(SensorReading.timestamp.asc())
            .all()
        )

        last_24h = [
            {
                "timestamp": r.timestamp.isoformat(),
                "ph": r.ph,
                "temperature": r.temperature,
                "salinity": r.salinity,
                "turbidity": r.turbidity,
                "light_intensity": r.light_intensity,
                "do_predicted": r.do_predicted,
            }
            for r in readings
        ]

        prediction = predict_do(kja_id, last_24h)
        return jsonify(
            {
                "kja_id": kja_id,
                "kja_name": unit.name,
                **prediction,
            }
        )
    finally:
        session.close()
