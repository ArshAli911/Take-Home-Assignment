"""MediaPipe face detection wrapper.

MediaPipe is imported lazily inside the constructor so the rest of the
test suite can run without the `mediapipe` wheel installed (the upload
route is monkeypatched in tests).

Two detectors are kept side-by-side because they cover different ranges:
- `model_selection=0` (short-range, < 2 m) — best for selfies and other
  close-to-camera footage. Misses faces that are far away.
- `model_selection=1` (full-range, < 5 m) — best for general scenes.
  Tends to miss faces that fill most of the frame (i.e. *too close* to
  the camera) because the network was trained on smaller faces.

We try short-range first and fall back to full-range. That ordering is
the cheap fix for the "face too close to camera" edge case and still
handles farther faces fine.
"""

from types import SimpleNamespace
from typing import Optional

import numpy as np
from PIL import Image


def _clamp_bbox(rel_box, image_shape) -> Optional[tuple[int, int, int, int]]:
    """Convert a relative MediaPipe bbox to clamped absolute pixel coords.

    A face that's too close to the camera often produces a bbox that
    extends past one or more frame edges (negative xmin/ymin, or width/
    height that overflows the frame). We trim the bbox to the visible
    region instead of throwing the detection away, so the user still
    sees a rectangle around the visible part of their face.

    Returns None if no usable area remains after clamping.
    """
    h, w = image_shape[:2]
    x = int(rel_box.xmin * w)
    y = int(rel_box.ymin * h)
    bw = int(rel_box.width * w)
    bh = int(rel_box.height * h)

    # If the box starts outside the frame, shift the origin in and shrink
    # the size by the same amount so the right/bottom edges stay put.
    if x < 0:
        bw += x
        x = 0
    if y < 0:
        bh += y
        y = 0
    if x + bw > w:
        bw = w - x
    if y + bh > h:
        bh = h - y
    if bw <= 0 or bh <= 0:
        return None
    return x, y, bw, bh


class FaceDetector:
    """Detects the single most-confident face in a PIL image."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        # Lazy import keeps `import app.routes.videos` cheap for tests.
        import mediapipe as mp

        face_detection = mp.solutions.face_detection.FaceDetection
        # Short-range first (close-up); full-range as fallback.
        self._short = face_detection(
            model_selection=0, min_detection_confidence=min_confidence
        )
        self._full = face_detection(
            model_selection=1, min_detection_confidence=min_confidence
        )

    def detect(self, image: Image.Image) -> Optional[tuple[int, int, int, int]]:
        """Return `(x, y, width, height)` in pixels, or None if no face."""
        rgb = np.asarray(image.convert("RGB"))
        # Try short-range first — it's the model that recognizes faces
        # filling most of the frame, which is the close-to-camera case.
        for detector in (self._short, self._full):
            result = detector.process(rgb)
            if not result.detections:
                continue
            best = max(
                result.detections,
                key=lambda d: d.score[0] if d.score else 0.0,
            )
            bbox = _clamp_bbox(best.location_data.relative_bounding_box, rgb.shape)
            if bbox is not None:
                return bbox
        return None

    def close(self) -> None:
        self._short.close()
        self._full.close()


# Re-export for tests; lets test code build a fake `rel_box` without
# pulling in mediapipe just for the namedtuple-like shape.
RelBox = SimpleNamespace
