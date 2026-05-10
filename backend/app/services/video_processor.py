"""End-to-end video processing pipeline.

Synchronous by design: the assignment is small enough that running this
inline on the request thread is the simplest correct thing. For large
videos we'd move this to a background worker.
"""

import logging
import shutil
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.config import FRAMES_DIR, PROCESSED_DIR
from app.models.video import ROI, Video
from app.services import ffmpeg_utils
from app.services.face_detector import FaceDetector

logger = logging.getLogger(__name__)


def _annotate_frames(frames_dir: Path, fps: float) -> tuple[list[dict], int]:
    """Run face detection on every frame and bake ROIs into the PNGs.

    Returns the list of ROI dicts (one per frame that contained a face)
    and the total number of frames examined.
    """
    detector = FaceDetector()
    rois: list[dict] = []
    frame_paths = sorted(frames_dir.glob("frame_*.png"))
    logger.info("Annotating %d frames in %s", len(frame_paths), frames_dir)
    try:
        for frame_number, path in enumerate(frame_paths):
            with Image.open(path) as img:
                img.load()
                bbox = detector.detect(img)
                if bbox is not None:
                    x, y, w, h = bbox
                    ImageDraw.Draw(img).rectangle(
                        [(x, y), (x + w, y + h)],
                        outline="lime",
                        width=3,
                    )
                    rois.append({
                        "frame_number": frame_number,
                        "timestamp": frame_number / fps if fps else 0.0,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                    })
                img.save(path)
    finally:
        detector.close()
    logger.info("Annotation complete: %d faces detected across %d frames", len(rois), len(frame_paths))
    return rois, len(frame_paths)


def process_video(
    video_id: str,
    src_path: Path,
    original_filename: str,
    db: Session,
) -> dict:
    """Drive the full pipeline and persist results atomically.

    Steps: probe fps → extract frames → detect/draw → reconstruct mp4 →
    insert Video + ROI rows in a single transaction. The frames scratch
    directory is always cleaned up.
    """
    frames_dir = FRAMES_DIR / video_id
    out_path = PROCESSED_DIR / f"{video_id}.mp4"
    logger.info("Processing pipeline started: video_id=%s", video_id)
    try:
        fps = ffmpeg_utils.probe_fps(src_path)
        logger.info("Probed fps=%.2f for video_id=%s", fps, video_id)

        ffmpeg_utils.extract_frames(src_path, frames_dir)
        logger.info("Frames extracted to %s for video_id=%s", frames_dir, video_id)

        rois, frame_count = _annotate_frames(frames_dir, fps)

        ffmpeg_utils.reconstruct_video(frames_dir, fps, out_path)
        logger.info("Video reconstructed: video_id=%s, output=%s", video_id, out_path)

        video = Video(
            id=video_id,
            original_filename=original_filename,
            processed_filename=out_path.name,
            frame_count=frame_count,
            fps=fps,
        )
        db.add(video)
        db.flush()
        if rois:
            db.bulk_save_objects([ROI(video_id=video_id, **r) for r in rois])
        db.commit()
        logger.info(
            "Pipeline complete: video_id=%s, frames=%d, rois=%d",
            video_id, frame_count, len(rois),
        )

        return {
            "video_id": video_id,
            "frame_count": frame_count,
            "fps": fps,
            "roi_count": len(rois),
        }
    except Exception:
        logger.exception("Pipeline failed for video_id=%s, rolling back", video_id)
        db.rollback()
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
