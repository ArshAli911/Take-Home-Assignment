"""Unit tests for the bbox-clamping logic.

The actual MediaPipe detection is exercised at integration time — these
tests cover the pure post-processing step, including the "face too
close to camera" edge case where MediaPipe returns a bbox that extends
past the frame edges.
"""

from app.services.face_detector import RelBox, _clamp_bbox

# Image shape is (height, width[, channels]); 200x300 here.
SHAPE = (200, 300, 3)


def test_clamp_normal_face_inside_frame():
    box = RelBox(xmin=0.1, ymin=0.2, width=0.3, height=0.4)
    assert _clamp_bbox(box, SHAPE) == (30, 40, 90, 80)


def test_clamp_face_too_close_overflows_right_and_bottom():
    # Face bbox claims to extend past the right and bottom edges — what
    # MediaPipe returns when the subject is right up against the lens.
    box = RelBox(xmin=0.5, ymin=0.5, width=0.9, height=0.9)
    x, y, bw, bh = _clamp_bbox(box, SHAPE)
    # Origin stays put; size is trimmed to the visible region.
    assert (x, y) == (150, 100)
    assert x + bw == 300  # clamped to image width
    assert y + bh == 200  # clamped to image height


def test_clamp_face_too_close_overflows_top_left():
    # Negative xmin/ymin happen when MediaPipe extrapolates a bbox whose
    # top-left corner is off the frame because the face is huge.
    box = RelBox(xmin=-0.2, ymin=-0.1, width=0.5, height=0.5)
    x, y, bw, bh = _clamp_bbox(box, SHAPE)
    assert (x, y) == (0, 0)
    # Width/height shrink by the amount we shifted the origin in.
    # Original right edge: (-0.2 + 0.5) * 300 = 90; expected bw = 90.
    assert bw == 90
    # Original bottom edge: (-0.1 + 0.5) * 200 = 80; expected bh = 80.
    assert bh == 80


def test_clamp_face_completely_outside_returns_none():
    # Pathological: bbox is entirely off-screen.
    box = RelBox(xmin=-1.0, ymin=-1.0, width=0.5, height=0.5)
    assert _clamp_bbox(box, SHAPE) is None


def test_clamp_zero_size_returns_none():
    box = RelBox(xmin=0.1, ymin=0.1, width=0.0, height=0.0)
    assert _clamp_bbox(box, SHAPE) is None
