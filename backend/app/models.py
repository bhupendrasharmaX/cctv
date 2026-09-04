import datetime
from typing import Optional, List
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, BigInteger, Index
from sqlalchemy.orm import relationship
from pydantic import BaseModel, ConfigDict
from backend.app.database import Base

# ==================== SQLAlchemy ORM Models ====================

class Camera(Base):
    __tablename__ = "cameras"

    camera_id = Column(String(64), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    department = Column(String(100), nullable=False) # Gujarat Police, RTO, AMC, GMC, etc.
    district = Column(String(100), default="Ahmedabad")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_description = Column(Text, nullable=True)
    camera_type = Column(String(50), default="ANPR") # ANPR, PTZ, Fixed Bullet
    codec = Column(String(20), default="H264")
    rtsp_url = Column(Text, nullable=False)
    whep_url = Column(Text, nullable=True)
    hls_url = Column(Text, nullable=True)
    connectivity_status = Column(String(20), default="ONLINE") # ONLINE, OFFLINE, DEGRADED
    last_ping = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    detections = relationship("Detection", back_populates="camera")
    alerts = relationship("Alert", back_populates="camera")


class Detection(Base):
    __tablename__ = "detections"

    detection_id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(64), ForeignKey("cameras.camera_id"), index=True, nullable=False)
    plate_number = Column(String(32), index=True, nullable=False) # Normalized alphanumeric
    plate_raw = Column(String(32), nullable=True)
    confidence = Column(Float, default=0.0)
    vehicle_type = Column(String(30), default="CAR") # CAR, TRUCK, BUS, MOTORCYCLE
    pts_timestamp_ms = Column(BigInteger, default=0)
    capture_timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    snapshot_path = Column(Text, nullable=True)

    camera = relationship("Camera", back_populates="detections")
    alerts = relationship("Alert", back_populates="detection")


class Watchlist(Base):
    __tablename__ = "watchlist"

    watchlist_id = Column(Integer, primary_key=True, autoincrement=True)
    plate_number = Column(String(32), unique=True, index=True, nullable=False)
    vehicle_owner = Column(String(255), nullable=True)
    vehicle_make_model = Column(String(100), nullable=True)
    crime_category = Column(String(100), nullable=False) # Stolen, Kidnapping, Wanted, Hit & Run
    fir_number = Column(String(100), nullable=True)
    police_station = Column(String(100), nullable=True)
    severity = Column(String(20), default="CRITICAL") # CRITICAL, HIGH, MEDIUM
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.datetime.utcnow)

    alerts = relationship("Alert", back_populates="watchlist_entry")


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(Integer, primary_key=True, autoincrement=True)
    detection_id = Column(Integer, ForeignKey("detections.detection_id"), nullable=True)
    watchlist_id = Column(Integer, ForeignKey("watchlist.watchlist_id"), nullable=True)
    camera_id = Column(String(64), ForeignKey("cameras.camera_id"), nullable=False)
    plate_number = Column(String(32), nullable=False)
    severity = Column(String(20), default="CRITICAL")
    alert_message = Column(Text, nullable=False)
    status = Column(String(20), default="NEW") # NEW, ACKNOWLEDGED, RESOLVED
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    camera = relationship("Camera", back_populates="alerts")
    detection = relationship("Detection", back_populates="alerts")
    watchlist_entry = relationship("Watchlist", back_populates="alerts")


# ==================== Pydantic Schemas ====================

class CameraSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    camera_id: str
    name: str
    department: str
    district: str
    latitude: float
    longitude: float
    location_description: Optional[str] = None
    camera_type: str
    codec: str
    rtsp_url: str
    whep_url: Optional[str] = None
    hls_url: Optional[str] = None
    connectivity_status: str
    last_ping: Optional[datetime.datetime] = None


class DetectionCreate(BaseModel):
    camera_id: str
    plate_number: str
    plate_raw: Optional[str] = None
    confidence: float = 0.0
    vehicle_type: str = "CAR"
    pts_timestamp_ms: int = 0
    snapshot_path: Optional[str] = None


class DetectionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    detection_id: int
    camera_id: str
    plate_number: str
    plate_raw: Optional[str] = None
    confidence: float
    vehicle_type: str
    pts_timestamp_ms: int
    capture_timestamp: datetime.datetime
    snapshot_path: Optional[str] = None


class WatchlistSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    watchlist_id: int
    plate_number: str
    vehicle_owner: Optional[str] = None
    vehicle_make_model: Optional[str] = None
    crime_category: str
    fir_number: Optional[str] = None
    police_station: Optional[str] = None
    severity: str
    notes: Optional[str] = None
    active: bool
    added_at: datetime.datetime


class AlertSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: int
    detection_id: Optional[int] = None
    watchlist_id: Optional[int] = None
    camera_id: str
    plate_number: str
    severity: str
    alert_message: str
    status: str
    created_at: datetime.datetime
    camera_name: Optional[str] = None
    department: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    snapshot_path: Optional[str] = None
    vehicle_make_model: Optional[str] = None
    crime_category: Optional[str] = None
