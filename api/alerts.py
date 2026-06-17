from flask import Blueprint, jsonify

from database.models import Alert, KjaUnit, get_session

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/alert")


@alerts_bp.route("/list", methods=["GET"])
def list_alerts():
    session = get_session()
    try:
        alerts = (
            session.query(Alert, KjaUnit.name)
            .join(KjaUnit, Alert.kja_id == KjaUnit.id)
            .order_by(Alert.timestamp.desc())
            .limit(50)
            .all()
        )

        return jsonify(
            [
                {
                    "id": alert.id,
                    "kja_id": alert.kja_id,
                    "kja_name": kja_name,
                    "parameter": alert.parameter,
                    "severity": alert.severity.value,
                    "message": alert.message,
                    "timestamp": alert.timestamp.isoformat(),
                    "is_read": alert.is_read,
                }
                for alert, kja_name in alerts
            ]
        )
    finally:
        session.close()


@alerts_bp.route("/read/<int:alert_id>", methods=["POST"])
def mark_alert_read(alert_id: int):
    session = get_session()
    try:
        alert = session.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            return jsonify({"error": "Alert not found"}), 404

        alert.is_read = True
        session.commit()
        return jsonify({"id": alert.id, "is_read": True})
    finally:
        session.close()
