"""Application configuration.

Paths are read from environment variables so tests can redirect them to
a temporary directory without touching the production `/data` mount.
"""

import os
from pathlib import Path

# Root data directory. In Docker this is a mounted volume; in tests the
# conftest sets DATA_DIR to a tmp path before the app is imported.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

UPLOAD_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
FRAMES_DIR = DATA_DIR / "frames"

# Database URL. Defaults to a SQLite file inside DATA_DIR.
DB_URL = os.environ.get("DB_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

# Upload constraints.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {".mp4"}
# `application/octet-stream` is what curl sends by default; we accept it
# alongside the proper `video/mp4` so the API stays usable from the CLI.
ALLOWED_MIME = {"video/mp4", "application/octet-stream"}

# Make sure the directories exist on import so the rest of the app can
# assume they're writable.
for _d in (DATA_DIR, UPLOAD_DIR, PROCESSED_DIR, FRAMES_DIR):
    _d.mkdir(parents=True, exist_ok=True)
