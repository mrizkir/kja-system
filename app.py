from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from api.alerts import alerts_bp
from api.sensors import sensors_bp
from api.weather import weather_bp
from config import config_by_name
from database.models import Base, get_engine

_PAYLOAD_BODY_LIMIT = 2000


def _setup_payload_log(app: Flask) -> None:
    """Log API method, query string, and body to logs/payload.log (no secrets)."""
    log_dir = Path(app.config["LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("kja.payload")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = TimedRotatingFileHandler(
            log_dir / "payload.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d"
        handler.namer = lambda name: str(
            Path(name).parent / f"payload-{Path(name).name.rsplit('.', 1)[-1]}.log"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)

    @app.before_request
    def log_request_payload():
        if not request.path.startswith("/api/"):
            return
        if request.path == "/api/health":
            return

        qs = request.query_string.decode("utf-8", errors="replace")
        body = "-"
        if request.method in ("POST", "PUT", "PATCH"):
            raw = request.get_data(cache=True, as_text=True) or ""
            body = raw[:_PAYLOAD_BODY_LIMIT] if raw else "-"

        logger.info(
            "%s %s qs=%s body=%s",
            request.method,
            request.path,
            qs or "-",
            body,
        )


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    config = config_by_name.get(config_name, config_by_name["default"])

    app = Flask(
        __name__,
        static_folder=str(config.STATIC_FOLDER),
        static_url_path="/static",
    )
    app.config.from_object(config)

    if config.DEBUG:
        CORS(app, resources={r"/api/*": {"origins": "*"}})

    Base.metadata.create_all(get_engine())

    app.register_blueprint(sensors_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(weather_bp)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "kja-digital-twin"})

    static_folder = Path(app.static_folder)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path: str):
        """Serve Vue production build from /static."""
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404

        if path and (static_folder / path).exists():
            return send_from_directory(static_folder, path)

        index = static_folder / "index.html"
        if index.exists():
            return send_from_directory(static_folder, "index.html")

        return jsonify(
            {
                "message": "KJA Digital Twin API",
                "hint": "Run Vue dev server (npm run dev) or build frontend to /static",
            }
        )

    _setup_payload_log(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
