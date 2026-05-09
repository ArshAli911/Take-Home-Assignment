"""Test bootstrap.

We redirect DATA_DIR/DB_URL to a tmp path *before* importing the app so
the production `/data` mount is never touched. We also stub the heavy
processing pipeline so tests don't need ffmpeg or mediapipe installed.
"""

import os
import shutil
import tempfile
from pathlib import Path

# Must run before any `from app...` import.
_TMP = Path(tempfile.mkdtemp(prefix="vid_test_"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DB_URL"] = f"sqlite:///{_TMP / 'test.db'}"

import pytest
from fastapi.testclient import TestClient

from app.config import PROCESSED_DIR
from app.database.session import SessionLocal, init_db
from app.main import app
from app.models.video import ROI, Video

# Create tables once; tests share the same DB but each one uses a unique
# UUID so they don't collide.
init_db()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db():
    """Yield a session backed by the same SQLite file the app uses."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def stub_processor(monkeypatch):
    """Replace `process_video` with a fast stub that fakes the artifacts."""

    def fake(video_id, src_path, original_filename, db):
        out = PROCESSED_DIR / f"{video_id}.mp4"
        out.write_bytes(b"\x00fake-mp4")
        video = Video(
            id=video_id,
            original_filename=original_filename,
            processed_filename=out.name,
            frame_count=3,
            fps=30.0,
        )
        db.add(video)
        db.flush()
        db.bulk_save_objects([
            ROI(
                video_id=video_id,
                frame_number=i,
                timestamp=i / 30.0,
                x=10,
                y=20,
                width=50,
                height=50,
            )
            for i in range(2)
        ])
        db.commit()
        return {
            "video_id": video_id,
            "frame_count": 3,
            "fps": 30.0,
            "roi_count": 2,
        }

    # Patch the name as imported into the route module — that's the
    # binding the request handler actually resolves.
    monkeypatch.setattr("app.routes.videos.process_video", fake)
    return fake


def pytest_sessionfinish(session, exitstatus):
    """Best-effort cleanup of the tmp data directory."""
    shutil.rmtree(_TMP, ignore_errors=True)
