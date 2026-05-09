"""SQLAlchemy ORM models for videos and their per-frame ROIs."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    # Timezone-aware replacement for the deprecated `datetime.utcnow()`.
    return datetime.now(timezone.utc)


class Video(Base):
    """One row per uploaded video."""

    __tablename__ = "videos"

    # UUID4 string. Used as both the DB key and the on-disk filename so
    # the API surface never exposes the user's original filename.
    id = Column(String, primary_key=True)
    original_filename = Column(String, nullable=False)
    processed_filename = Column(String, nullable=True)
    upload_timestamp = Column(DateTime, nullable=False, default=_utcnow)
    frame_count = Column(Integer, nullable=False, default=0)
    fps = Column(Float, nullable=False, default=0.0)

    # `cascade="all, delete-orphan"` keeps the schema honest if we ever
    # delete a video — the ROIs go with it.
    rois = relationship(
        "ROI",
        back_populates="video",
        cascade="all, delete-orphan",
        order_by="ROI.frame_number",
    )


class ROI(Base):
    """One row per frame in which a face was detected."""

    __tablename__ = "rois"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, ForeignKey("videos.id"), index=True, nullable=False)
    frame_number = Column(Integer, nullable=False)
    timestamp = Column(Float, nullable=False)  # seconds from start
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)

    video = relationship("Video", back_populates="rois")
