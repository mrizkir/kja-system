import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from config import Config


class Base(DeclarativeBase):
    pass


class DoSource(enum.Enum):
    tft = "tft"
    manual = "manual"


class Species(enum.Enum):
    grouper = "grouper"
    snapper = "snapper"


class AlertSeverity(enum.Enum):
    info = "info"
    warn = "warn"
    danger = "danger"


class KjaUnit(Base):
    __tablename__ = "kja_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    species: Mapped[Species] = mapped_column(Enum(Species), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    farmer_name: Mapped[str] = mapped_column(String(128), nullable=False)

    readings: Mapped[list["SensorReading"]] = relationship(back_populates="kja_unit")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="kja_unit")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kja_id: Mapped[int] = mapped_column(ForeignKey("kja_units.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ph: Mapped[float] = mapped_column(Float, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    salinity: Mapped[float] = mapped_column(Float, nullable=False)
    turbidity: Mapped[float] = mapped_column(Float, nullable=False)
    light_intensity: Mapped[float] = mapped_column(Float, nullable=False)
    do_predicted: Mapped[float] = mapped_column(Float, nullable=False)
    do_source: Mapped[DoSource] = mapped_column(Enum(DoSource), default=DoSource.tft)

    kja_unit: Mapped["KjaUnit"] = relationship(back_populates="readings")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kja_id: Mapped[int] = mapped_column(ForeignKey("kja_units.id"), nullable=False, index=True)
    parameter: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity), nullable=False)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    kja_unit: Mapped["KjaUnit"] = relationship(back_populates="alerts")


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()
