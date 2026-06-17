from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from api.alerts import alerts_bp
from api.sensors import sensors_bp
from config import config_by_name
from database.models import Base, get_engine


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

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
