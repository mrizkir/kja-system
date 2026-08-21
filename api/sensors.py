from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from database.models import (
    Alert,
    AlertSeverity,
    DoSource,
    KjaUnit,
    SensorReading,
    get_session,
)
from database.seed import _alert_message, evaluate_parameter
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


def _parse_float(payload: dict, key: str) -> float:
    try:
        return float(payload[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for '{key}'") from exc


def _first_float(payload: dict, *keys: str) -> float:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _parse_float(payload, key)
    raise ValueError(f"Missing numeric field (tried: {', '.join(keys)})")


def _parse_timestamp(value: object) -> datetime:
    if value is None or value == "now":
        return datetime.utcnow()
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        # receiver may send "YYYY-MM-DD HH:MM:SS"
        for fmt in (None, "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                if fmt is None:
                    return datetime.fromisoformat(text).replace(tzinfo=None)
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise ValueError("Invalid timestamp; use ISO-8601 or YYYY-MM-DD HH:MM:SS")
    raise ValueError("Invalid timestamp; use ISO-8601 or unix epoch")


def _check_ingest_auth() -> tuple[dict, int] | None:
    """Validate Bearer token from receiver.ino when Authorization header is present."""
    expected = current_app.config.get("INGEST_BEARER_TOKEN")
    header = request.headers.get("Authorization", "")
    if not header:
        # Allow dashboard / curl tests without token
        return None
    if not header.startswith("Bearer "):
        return {"error": "Authorization must be Bearer token"}, 401
    token = header[7:].strip()
    if expected and token != expected:
        return {"error": "Invalid bearer token"}, 401
    return None


def _resolve_kja_id(payload: dict) -> int:
    if "kja_id" not in payload:
        raise ValueError("Missing 'kja_id'")
    return int(payload["kja_id"])


@sensors_bp.route("/sensor/ingest", methods=["POST"])
def ingest_reading():
    """Accept IoT payload from receiver.ino (kja_id + ph/suhu/salinitas/kekeruhan)."""
    auth_error = _check_ingest_auth()
    if auth_error:
        body, code = auth_error
        return jsonify(body), code

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "JSON body required"}), 400

    try:
        kja_id = _resolve_kja_id(payload)
        ph = _first_float(payload, "ph")
        temperature = _first_float(payload, "suhu", "temperature")
        salinity = _first_float(payload, "salinitas", "salinity")
        turbidity = _first_float(payload, "kekeruhan", "turbidity")
        timestamp = _parse_timestamp(payload.get("timestamp"))

        light_intensity = (
            _parse_float(payload, "light_intensity")
            if "light_intensity" in payload
            else 0.0
        )
        do_predicted_in = (
            _parse_float(payload, "do_predicted")
            if "do_predicted" in payload
            else None
        )
        device_status = payload.get("status")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    session = get_session()
    try:
        unit = session.query(KjaUnit).filter(KjaUnit.id == kja_id).first()
        if not unit:
            return jsonify({"error": "KJA unit not found"}), 404

        if do_predicted_in is None:
            since = datetime.utcnow() - timedelta(hours=24)
            history = (
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
                for r in history
            ]
            prediction = predict_do(kja_id, last_24h)
            do_predicted = float(prediction["do_now"])
            do_source = DoSource.tft
        else:
            do_predicted = do_predicted_in
            do_source = DoSource.manual

        reading = SensorReading(
            kja_id=kja_id,
            timestamp=timestamp,
            ph=ph,
            temperature=temperature,
            salinity=salinity,
            turbidity=turbidity,
            light_intensity=light_intensity,
            do_predicted=do_predicted,
            do_source=do_source,
        )
        session.add(reading)
        session.flush()

        checks = {
            "ph": ph,
            "temperature": temperature,
            "salinity": salinity,
            "turbidity": turbidity,
            "do_predicted": do_predicted,
        }
        created_alerts = []
        for parameter, value in checks.items():
            severity = evaluate_parameter(parameter, value)
            if severity:
                alert = Alert(
                    kja_id=kja_id,
                    parameter=parameter,
                    severity=severity,
                    message=_alert_message(unit.name, parameter, value, severity),
                    timestamp=timestamp,
                    is_read=False,
                )
                session.add(alert)
                created_alerts.append(
                    {
                        "parameter": parameter,
                        "severity": severity.value,
                        "message": alert.message,
                    }
                )

        session.commit()
        session.refresh(reading)

        return jsonify(
            {
                "ok": True,
                "kja_id": kja_id,
                "kja_name": unit.name,
                "device_status": device_status,
                "reading": _reading_to_dict(reading, unit.name),
                "alerts": created_alerts,
            }
        ), 201
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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
