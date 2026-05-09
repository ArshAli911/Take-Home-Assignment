"""MediaPipe face detection wrapper.

MediaPipe is imported lazily inside the constructor so the rest of the
test suite can run without the `mediapipe` wheel installed (the upload
route is monkeypatched in tests).
"""

from typing import Optional

import numpy as np
from PIL import Image


class FaceDetector:
    """Detects the single most-confident face in a PIL image."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        # Lazy import keeps `import app.routes.videos` cheap for tests.
        import mediapipe as mp

        # model_selection=1 covers faces up to ~5 m away (full-range model);
        # works well for typical short videos.
        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=min_confidence,
        )

    def detect(self, image: Image.Image) -> Optional[tuple[int, int, int, int]]:
        """Return `(x, y, width, height)` in pixels, or None if no face."""
        # MediaPipe expects an RGB numpy array.
        rgb = np.asarray(image.convert("RGB"))
        result = self._detector.process(rgb)
        if not result.detections:
            return None

        # Pick the highest-scoring detection (assignment assumes 1 face).
        best = max(result.detections, key=lambda d: d.score[0] if d.score else 0.0)
        bbox = best.location_data.relative_bounding_box

        h, w = rgb.shape[:2]
        # Clamp to image bounds — MediaPipe occasionally returns slightly
        # negative coordinates near the edge of the frame.
        x = max(0, int(bbox.xmin * w))
        y = max(0, int(bbox.ymin * h))
        bw = max(0, int(bbox.width * w))
        bh = max(0, int(bbox.height * h))
        if x + bw > w:
            bw = w - x
        if y + bh > h:
            bh = h - y
        if bw <= 0 or bh <= 0:
            return None
        return x, y, bw, bh

    def close(self) -> None:
        self._detector.close()
