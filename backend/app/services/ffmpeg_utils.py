"""Thin wrappers around the ffmpeg / ffprobe CLI.

We shell out to ffmpeg instead of binding to libav so the assignment
constraint of "no OpenCV" is easy to honor and the dependency surface
stays small. ffmpeg is provided by the Docker image.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    """Raised when ffmpeg/ffprobe exits non-zero."""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a command and raise FFmpegError with stderr on failure."""
    logger.debug("Running command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Command failed (rc=%d): %s\nstderr: %s", result.returncode, " ".join(cmd), result.stderr.strip()[:500])
        raise FFmpegError(result.stderr.strip()[:500] or "ffmpeg failed")
    return result


def probe_fps(video_path: Path) -> float:
    """Return the source video's frame rate.

    ffprobe reports r_frame_rate as a rational like "30000/1001"; we
    evaluate that to a float and fall back to 30 if parsing fails for
    any reason.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=nokey=1:noprint_wrappers=1",
        str(video_path),
    ]
    raw = _run(cmd).stdout.strip()
    try:
        num, den = raw.split("/")
        fps = float(num) / float(den)
        return fps if fps > 0 else 30.0
    except (ValueError, ZeroDivisionError):
        logger.warning("Could not parse fps from '%s', falling back to 30.0", raw)
        return 30.0


def extract_frames(video_path: Path, frames_dir: Path) -> None:
    """Decode every frame to PNG inside `frames_dir`.

    Frames are numbered starting at 0 with six-digit zero padding so
    lexical ordering matches frame order.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-start_number", "0",
        str(frames_dir / "frame_%06d.png"),
    ]
    _run(cmd)


def reconstruct_video(frames_dir: Path, fps: float, out_path: Path) -> None:
    """Re-encode the (now-annotated) frames back into an MP4.

    `-movflags +faststart` moves the moov atom to the front so the file
    starts playing in the browser before it's fully buffered.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate", f"{fps:.6f}",
        "-start_number", "0",
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]
    _run(cmd)
