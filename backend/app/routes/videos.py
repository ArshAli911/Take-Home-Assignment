"""HTTP endpoints for upload, playback, and ROI metadata."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME,
    MAX_UPLOAD_BYTES,
    PROCESSED_DIR,
    UPLOAD_DIR,
)
from app.database.session import get_db
from app.models.video import ROI, Video
from app.services.ffmpeg_utils import FFmpegError
from app.services.video_processor import process_video
from app.utils.filenames import sanitize_filename

logger = logging.getLogger(__name__)

router = APIRouter()

# Read in 1 MB chunks; large enough to be cheap, small enough that we
# notice an oversize upload before reading the whole thing into memory.
_CHUNK = 1024 * 1024


class UploadResponse(BaseModel):
    video_id: str
    original_filename: str
    frame_count: int
    fps: float
    roi_count: int
    warning: str | None = None


class ROIItem(BaseModel):
    frame_number: int
    timestamp: float
    x: int
    y: int
    width: int
    height: int


class ROIResponse(BaseModel):
    video_id: str
    fps: float
    frame_count: int
    rois: list[ROIItem]


def _validate_upload_metadata(file: UploadFile) -> None:
    """Reject obviously-wrong uploads before we touch the disk."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .mp4 files are accepted",
        )
    # `content_type` may be missing when called via curl without -H; the
    # extension check above is the real gatekeeper.
    if file.content_type and file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {file.content_type}",
        )


async def _save_upload_streamed(file: UploadFile, dest: Path) -> None:
    """Stream the upload to disk while enforcing MAX_UPLOAD_BYTES.

    We write chunk-by-chunk so a hostile client can't OOM us by claiming
    a small Content-Length and then streaming gigabytes.
    """
    total = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
                    )
                out.write(chunk)
    except HTTPException:
        # Tidy up the partial file before propagating.
        dest.unlink(missing_ok=True)
        raise


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Accept an MP4, run the processing pipeline, return the video id."""
    _validate_upload_metadata(file)

    video_id = uuid.uuid4().hex
    src_path = UPLOAD_DIR / f"{video_id}.mp4"
    logger.info("Upload started: video_id=%s, filename=%s", video_id, file.filename)
    await _save_upload_streamed(file, src_path)
    logger.info("Upload saved to disk: video_id=%s, path=%s", video_id, src_path)

    original = sanitize_filename(file.filename)
    try:
        result = process_video(video_id, src_path, original, db)
    except FFmpegError as exc:
        logger.error("FFmpeg error for video_id=%s: %s", video_id, exc)
        src_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video processing failed: {exc}",
        )
    except Exception:
        logger.exception("Unexpected error processing video_id=%s", video_id)
        src_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video processing failed",
        )

    warning = "no faces detected" if result["roi_count"] == 0 else None
    logger.info(
        "Upload complete: video_id=%s, frames=%d, fps=%.2f, rois=%d",
        video_id, result["frame_count"], result["fps"], result["roi_count"],
    )
    return UploadResponse(
        video_id=result["video_id"],
        original_filename=original,
        frame_count=result["frame_count"],
        fps=result["fps"],
        roi_count=result["roi_count"],
        warning=warning,
    )


@router.get("/video/{video_id}")
def get_video(video_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Stream the processed MP4."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if video is None or not video.processed_filename:
        logger.warning("Video not found: video_id=%s", video_id)
        raise HTTPException(status_code=404, detail="Video not found")

    path = PROCESSED_DIR / video.processed_filename
    if not path.is_file():
        logger.error("Processed file missing on disk: video_id=%s, path=%s", video_id, path)
        raise HTTPException(status_code=404, detail="Processed file missing")

    logger.info("Serving video: video_id=%s", video_id)
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename=video.original_filename,
    )


@router.get("/roi/{video_id}", response_model=ROIResponse)
def get_roi(video_id: str, db: Session = Depends(get_db)) -> ROIResponse:
    """Return per-frame ROI metadata for a processed video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if video is None:
        logger.warning("ROI requested for unknown video: video_id=%s", video_id)
        raise HTTPException(status_code=404, detail="Video not found")

    rois = (
        db.query(ROI)
        .filter(ROI.video_id == video_id)
        .order_by(ROI.frame_number.asc())
        .all()
    )
    return ROIResponse(
        video_id=video_id,
        fps=video.fps,
        frame_count=video.frame_count,
        rois=[
            ROIItem(
                frame_number=r.frame_number,
                timestamp=r.timestamp,
                x=r.x,
                y=r.y,
                width=r.width,
                height=r.height,
            )
            for r in rois
        ],
    )

