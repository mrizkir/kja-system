import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "kja-dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'kja.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STATIC_FOLDER = BASE_DIR / "static"
    # Override on Pi if needed: Environment=KJA_LOG_DIR=/home/rizki/kja-logs
    LOG_DIR = Path(os.environ.get("KJA_LOG_DIR", BASE_DIR / "logs"))
    DEBUG = False
    # Must match Authorization Bearer in receiver.ino (override via env)
    INGEST_BEARER_TOKEN = os.environ.get(
        "INGEST_BEARER_TOKEN",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImE3ZDJkMWY2LTliNTgtNDYyZC05MGZkLTA1YmViOTRlNWVjMSIsInJvbGUiOiJhZG1pbiIsImlhdCI6MTc1Njg5OTIxOH0.siu-ITBJxhl5Jhap0ohHRdmd70kFY6oI0CevIgGgLnI",
    )
    TFT_ARTIFACT_DIR = Path(
        os.environ.get(
            "TFT_ARTIFACT_DIR",
            BASE_DIR / "training" / "artifacts" / "tft_v1",
        )
    )
    TFT_ENCODER_HOURS = int(os.environ.get("TFT_ENCODER_HOURS", "336"))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
