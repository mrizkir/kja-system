from __future__ import annotations

from flask import Blueprint, jsonify

from database.models import get_session
from database.rainfall import last_fetched_at, row_count

weather_bp = Blueprint("weather", __name__, url_prefix="/api/weather")


@weather_bp.route("/rainfall/status", methods=["GET"])
def rainfall_status():
    session = get_session()
    try:
        fetched = last_fetched_at(session)
        return jsonify(
            {
                "fetched_at": fetched.isoformat() if fetched else None,
                "row_count": row_count(session),
            }
        )
    finally:
        session.close()
