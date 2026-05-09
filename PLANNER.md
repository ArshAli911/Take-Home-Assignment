# PLANNER — Face ROI Video API (ordered implementation guide)

This file is a self-contained, step-by-step playbook for an AI coding agent
(or a human) to implement this take-home from scratch. Follow steps **in
order**. Each step lists the files to create, the exact responsibilities of
each file, and a verification check. Do not skip ahead — later steps assume
files from earlier steps exist.

> **Hard constraints (do not violate):**
> - Python 3.11, FastAPI, SQLAlchemy, SQLite, MediaPipe, Pillow, ffmpeg.
> - **No OpenCV / cv2 anywhere.**
> - No Redis, Celery, Kafka, K8s, microservices, websockets, auth, queues, cloud deploy.
> - Synchronous processing on the request thread.
> - One face per frame (highest-confidence detection).
> - MP4 only, ≤ 100 MB upload.
> - On-disk filenames are always `{uuid4}.mp4` — never trust the user's filename.

---

## 0. Prerequisites

- Python 3.11+ available locally.
- Node 20+ available locally.
- Docker + Docker Compose installed (for the final E2E check).
- An empty project directory; this guide assumes you start from nothing.

Final layout you should produce:

```
.
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database/{__init__.py, session.py}
│   │   ├── models/{__init__.py, video.py}
│   │   ├── routes/{__init__.py, videos.py}
│   │   ├── services/{__init__.py, ffmpeg_utils.py, face_detector.py, video_processor.py}
│   │   └── utils/{__init__.py, filenames.py}
│   ├── tests/{__init__.py, conftest.py, test_validation.py, test_upload.py, test_roi.py}
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/{main.jsx, App.jsx, api.js, styles.css}
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   └── Dockerfile
├── docker-compose.yml
├── .gitignore
└── README.md
```

---

## Step 1 — Scaffold backend package

Create empty `__init__.py` files for these packages:

- `backend/app/__init__.py`
- `backend/app/database/__init__.py`
- `backend/app/models/__init__.py`
- `backend/app/routes/__init__.py`
- `backend/app/services/__init__.py`
- `backend/app/utils/__init__.py`
- `backend/tests/__init__.py`

**Verify:** `find backend -name __init__.py` lists all 7.

---

## Step 2 — `backend/app/config.py`

Centralize paths and limits. Read paths from environment variables so tests
can redirect them.

Required values:
- `DATA_DIR` — `Path(os.environ.get("DATA_DIR", "/data"))`
- `UPLOAD_DIR = DATA_DIR / "uploads"`
- `PROCESSED_DIR = DATA_DIR / "processed"`
- `FRAMES_DIR = DATA_DIR / "frames"`
- `DB_URL = os.environ.get("DB_URL", f"sqlite:///{DATA_DIR / 'app.db'}")`
- `MAX_UPLOAD_BYTES = 100 * 1024 * 1024`
- `ALLOWED_EXTENSIONS = {".mp4"}`
- `ALLOWED_MIME = {"video/mp4", "application/octet-stream"}` (curl's default counts).
- At import time, `mkdir(parents=True, exist_ok=True)` for all four dirs.

---

## Step 3 — `backend/app/models/video.py`

SQLAlchemy ORM. Use a timezone-aware `_utcnow()` helper (not `datetime.utcnow`).

```
Base = declarative_base()

Video:           id (str PK, uuid hex), original_filename, processed_filename,
                 upload_timestamp (default _utcnow), frame_count (int),
                 fps (float), rois = relationship(... back_populates,
                 cascade="all, delete-orphan", order_by=ROI.frame_number)

ROI:             id (int PK autoincrement), video_id (FK→videos.id, indexed),
                 frame_number (int), timestamp (float), x/y/width/height (int),
                 video = relationship back to Video.
```

---

## Step 4 — `backend/app/database/session.py`

- Build the engine from `DB_URL`. Pass `connect_args={"check_same_thread": False}`
  only when the URL starts with `sqlite`.
- Define `SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)`.
- `def get_db()` — yields a session, closes in `finally`. (FastAPI dependency.)
- `def init_db()` — imports `Base` from `app.models.video` *inside the function*
  (so models are registered) and calls `Base.metadata.create_all(engine)`.

---

## Step 5 — `backend/app/utils/filenames.py`

Pure helper. `sanitize_filename(name) -> str`:
1. If `name` is empty/None → return `"upload.mp4"`.
2. `os.path.basename(name).strip()` to drop any path component.
3. Replace any char not in `[A-Za-z0-9._-]` with `_`.
4. Collapse runs of dots to a single dot (so `..` can never survive).
5. Strip leading/trailing `._-`.
6. If empty after cleanup, return `"upload.mp4"`.

---

## Step 6 — `backend/app/services/ffmpeg_utils.py`

Three functions wrapping `subprocess.run` with `capture_output=True, text=True`.
Define `class FFmpegError(RuntimeError)`. A private `_run(cmd)` helper raises
`FFmpegError(stderr_truncated_to_500_chars)` on non-zero exit.

- `probe_fps(video_path: Path) -> float`
  - Run `ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nokey=1:noprint_wrappers=1 <path>`.
  - Output is a rational like `30000/1001`. Parse to float; on failure return `30.0`.

- `extract_frames(video_path: Path, frames_dir: Path) -> None`
  - `ffmpeg -y -i <video> -start_number 0 <frames_dir>/frame_%06d.png`
  - Create `frames_dir` first.

- `reconstruct_video(frames_dir: Path, fps: float, out_path: Path) -> None`
  - `ffmpeg -y -framerate <fps> -start_number 0 -i <frames_dir>/frame_%06d.png -c:v libx264 -pix_fmt yuv420p -movflags +faststart <out>`
  - `+faststart` is required so the browser can begin playback before full buffer.

---

## Step 7 — `backend/app/services/face_detector.py`

Wraps MediaPipe. **Lazy-import `mediapipe`** inside `__init__` so the test
suite (which monkeypatches the processor) doesn't need it installed.

```python
class FaceDetector:
    def __init__(self, min_confidence=0.5):
        import mediapipe as mp                     # lazy
        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=min_confidence,
        )

    def detect(self, image: PIL.Image) -> tuple[int,int,int,int] | None:
        # PIL → numpy RGB → mediapipe.process(...)
        # If no detections: return None.
        # Otherwise pick max(detections, key=score), convert relative bbox to
        # absolute pixels, clamp to image bounds, return (x, y, w, h) or None
        # if zero-sized after clamping.

    def close(self): self._detector.close()
```

`numpy` IS imported at module top — it's small and cheap.

---

## Step 8 — `backend/app/services/video_processor.py`

The orchestrator. Single public function:

```python
def process_video(video_id: str, src_path: Path,
                  original_filename: str, db: Session) -> dict
```

Algorithm (in this exact order):

1. `frames_dir = FRAMES_DIR / video_id`; `out_path = PROCESSED_DIR / f"{video_id}.mp4"`.
2. Wrap everything below in `try/except/finally`.
3. `fps = ffmpeg_utils.probe_fps(src_path)`.
4. `ffmpeg_utils.extract_frames(src_path, frames_dir)`.
5. Helper `_annotate_frames(frames_dir, fps)`:
   - Construct one `FaceDetector` for the whole loop.
   - `for frame_number, path in enumerate(sorted(frames_dir.glob("frame_*.png")))`:
     - Open with PIL, `img.load()`, run `detector.detect(img)`.
     - If a bbox is returned: `ImageDraw.Draw(img).rectangle([(x,y),(x+w,y+h)], outline="lime", width=3)`
       and append `{frame_number, timestamp=frame_number/fps, x, y, width, height}`.
     - `img.save(path)` (overwrite).
   - Close detector in `finally`.
   - Return `(rois_list, total_frame_count)`.
6. `ffmpeg_utils.reconstruct_video(frames_dir, fps, out_path)`.
7. `Video` row: `db.add(...)`, `db.flush()` (so id is available for FK).
8. If rois: `db.bulk_save_objects([ROI(video_id=video_id, **r) for r in rois])`.
9. `db.commit()`. Return `{video_id, frame_count, fps, roi_count}`.
10. **`except`**: `db.rollback()`; `out_path.unlink(missing_ok=True)`; re-raise.
11. **`finally`**: `shutil.rmtree(frames_dir, ignore_errors=True)`.

---

## Step 9 — `backend/app/routes/videos.py`

`router = APIRouter()`. Pydantic models defined inline (small surface).

Pydantic models: `UploadResponse`, `ROIItem`, `ROIResponse` (see README for shape).

Constants: `_CHUNK = 1024 * 1024`.

Helpers:

- `_validate_upload_metadata(file: UploadFile)`:
  - If extension not in `ALLOWED_EXTENSIONS` → `HTTPException(400, "Only .mp4 files are accepted")`.
  - If `file.content_type` set and not in `ALLOWED_MIME` → `HTTPException(415, ...)`.

- `async _save_upload_streamed(file, dest)`:
  - Read in 1 MB chunks, count bytes; if total > `MAX_UPLOAD_BYTES`,
    `dest.unlink(missing_ok=True)` and raise `HTTPException(413, ...)`.
  - Catch any HTTPException, delete the partial file, re-raise.

Endpoints (mounted from `main.py` at root):

- **`POST /upload`** (`async`, `file: UploadFile = File(...)`, `db = Depends(get_db)`):
  1. `_validate_upload_metadata(file)`.
  2. `video_id = uuid.uuid4().hex`; `src_path = UPLOAD_DIR / f"{video_id}.mp4"`.
  3. `await _save_upload_streamed(file, src_path)`.
  4. `original = sanitize_filename(file.filename)`.
  5. `try: result = process_video(video_id, src_path, original, db)`
     - `except FFmpegError as e: src_path.unlink(missing_ok=True); raise HTTPException(500, f"Video processing failed: {e}")`
     - `except Exception: src_path.unlink(missing_ok=True); raise HTTPException(500, "Video processing failed")`
  6. `warning = "no faces detected" if result["roi_count"] == 0 else None`.
  7. Return `UploadResponse(...)` populated from `result` + `original` + `warning`.

- **`GET /video/{video_id}`**:
  - `Video` lookup → 404 if missing or `processed_filename` is None.
  - File missing on disk → 404 ("Processed file missing").
  - Return `FileResponse(path, media_type="video/mp4", filename=video.original_filename)`.

- **`GET /roi/{video_id}` → `ROIResponse`**:
  - 404 if video not found.
  - Query ROIs ordered by `frame_number ASC`. Return shape per spec.

---

## Step 10 — `backend/app/main.py`

Use a **lifespan** (FastAPI's `@asynccontextmanager`) — not the deprecated
`@app.on_event("startup")`.

```python
@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield

app = FastAPI(title="Face ROI Video API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:5173", "http://localhost:8000"],
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health(): return {"status": "ok"}

app.include_router(videos_router)
```

---

## Step 11 — `backend/requirements.txt`

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
python-multipart==0.0.12
pillow==10.4.0
mediapipe==0.10.14
numpy==1.26.4
pytest==8.3.3
httpx==0.27.2
```

> **Note:** `mediapipe==0.10.14` does not yet ship Python 3.13 wheels. The
> Docker image pins Python 3.11, so production is fine. For local dev on
> 3.13 you can install the test subset only (everything except `mediapipe`)
> and stub the processor.

---

## Step 12 — Backend tests

### `tests/conftest.py`

This is the trickiest file. Get the import order right:

```python
# 1) BEFORE any `from app...` import, redirect storage to a tmp dir:
import os, shutil, tempfile
from pathlib import Path
_TMP = Path(tempfile.mkdtemp(prefix="vid_test_"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DB_URL"] = f"sqlite:///{_TMP / 'test.db'}"

# 2) Now import normally:
import pytest
from fastapi.testclient import TestClient
from app.config import PROCESSED_DIR
from app.database.session import SessionLocal, init_db
from app.main import app
from app.models.video import Video, ROI

init_db()

# 3) Fixtures:
@pytest.fixture
def client(): return TestClient(app)

@pytest.fixture
def db():
    s = SessionLocal()
    try: yield s
    finally: s.close()

@pytest.fixture
def stub_processor(monkeypatch):
    def fake(video_id, src_path, original_filename, db):
        out = PROCESSED_DIR / f"{video_id}.mp4"
        out.write_bytes(b"\x00fake-mp4")
        v = Video(id=video_id, original_filename=original_filename,
                  processed_filename=out.name, frame_count=3, fps=30.0)
        db.add(v); db.flush()
        db.bulk_save_objects([
            ROI(video_id=video_id, frame_number=i, timestamp=i/30.0,
                x=10, y=20, width=50, height=50) for i in range(2)])
        db.commit()
        return {"video_id": video_id, "frame_count": 3, "fps": 30.0, "roi_count": 2}
    # IMPORTANT: monkeypatch where the route module imported it, not the source.
    monkeypatch.setattr("app.routes.videos.process_video", fake)
    return fake

def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
```

### `tests/test_validation.py`

Cover:
- `sanitize_filename("../../etc/passwd") == "passwd"`
- `sanitize_filename("hello world!.mp4") == "hello_world_.mp4"`
- `sanitize_filename("a..b.mp4") == "a.b.mp4"`
- `sanitize_filename("")`, `None`, `"..."` → `"upload.mp4"`
- `POST /upload` with `notes.txt` → 400; "mp4" appears in `detail`.
- `POST /upload` with no file → 422 (FastAPI default).
- `POST /upload` with oversize body → 413. Use
  `monkeypatch.setattr("app.routes.videos.MAX_UPLOAD_BYTES", 1024)` and post 4096 bytes.

### `tests/test_upload.py`

- Happy path with `stub_processor`: returns 200, body has `video_id`,
  `original_filename == "clip.mp4"`, `frame_count == 3`, `roi_count == 2`,
  `warning is None`.
- `GET /video/{id}` → 200, `content-type == "video/mp4"`, content matches stub bytes.
- `GET /video/does-not-exist` → 404.

### `tests/test_roi.py`

- After stubbed upload, `GET /roi/{id}` → 200 with `fps == 30.0`,
  `frame_count == 3`, `len(rois) == 2`, first row has `frame_number == 0`,
  `timestamp == 0.0`, and integer x/y/width/height.
- `GET /roi/does-not-exist` → 404.

### Verify

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install fastapi==0.115.0 sqlalchemy==2.0.35 python-multipart==0.0.12 \
            pillow==10.4.0 numpy pytest==8.3.3 httpx==0.27.2 \
            'uvicorn[standard]==0.30.6'
pytest
```

Expected: **12 passed in <1s, 0 warnings.**

---

## Step 13 — Frontend

### `frontend/package.json`

```
{
  "name": "face-roi-frontend", "private": true, "version": "1.0.0", "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": { "@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.8" }
}
```

### `frontend/vite.config.js`

Vite proxy so dev `/api/*` reaches the backend on `:8000` (rewrite removes `/api` prefix).

### `frontend/index.html`

Standard Vite shell with `<div id="root"></div>` and `<script type="module" src="/src/main.jsx">`.

### `frontend/src/main.jsx`

Bootstraps `<App />` in `React.StrictMode`, imports `./styles.css`.

### `frontend/src/api.js`

- `API_BASE = "/api"` (single source of truth).
- `uploadVideo(file)` — POST multipart, throw on non-2xx using a `safeDetail()` helper.
- `videoUrl(id)` — return `/api/video/{id}`.
- `fetchRoi(id)` — GET, throw on non-2xx.

### `frontend/src/App.jsx`

Single page, `useState` only. Has:
- `<input type="file" accept="video/mp4">` and an Upload button.
- Disabled while busy.
- Shows error banner on failure.
- On success: meta panel with `video_id, frame_count, fps, roi_count, warning?`,
  plus a `<video controls src={videoUrl(video_id)} />`.

### `frontend/src/styles.css`

A few system-font rules; no CSS framework.

### `frontend/nginx.conf`

```
server {
  listen 80;
  client_max_body_size 110M;          # >100MB cap so the API surfaces 413, not nginx.
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {                    # trailing slash strips /api/ before forwarding
    proxy_pass http://backend:8000/;
    proxy_set_header Host $host;
    proxy_request_buffering off;
    proxy_read_timeout 300s;
  }
  location / { try_files $uri $uri/ /index.html; }
}
```

---

## Step 14 — Docker

### `backend/Dockerfile`

```
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`libgl1` and `libglib2.0-0` are needed by mediapipe wheels at *import time*
even though we don't call cv2.

### `frontend/Dockerfile` (multi-stage)

```
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install                        # not `npm ci` — no lockfile committed
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### `docker-compose.yml`

```
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    volumes: [ "app_data:/data" ]
  frontend:
    build: ./frontend
    ports: ["5173:80"]
    depends_on: [backend]
volumes:
  app_data:
```

---

## Step 15 — `.gitignore` + `README.md`

`.gitignore` must include `__pycache__/`, `.venv/`, `node_modules/`, `dist/`,
`*.db`, `data/`, plus IDE/OS noise.

`README.md` must contain:
1. One-paragraph description.
2. Quick-start (`docker compose up --build`, port 5173, port 8000/docs).
3. Local dev for backend and frontend.
4. API reference table (3 endpoints + `/health`) with success/failure codes.
5. Example `UploadResponse` and `ROIResponse` JSON.
6. ASCII architecture diagram (see plan / current README).
7. Constraints & assumptions (mp4-only, 100 MB, one face, sync, uuid filenames).
8. Test instructions.
9. Suggested commit history (11 commits below).

### Suggested commit history (chronological — make these *real* commits)

1. `chore: scaffold backend FastAPI project structure`
2. `feat(db): add Video and ROI SQLAlchemy models`
3. `feat(services): ffmpeg extract/reconstruct utilities`
4. `feat(services): MediaPipe face detector wrapper`
5. `feat(services): video processing pipeline + Pillow ROI drawing`
6. `feat(api): /upload, /video/{id}, /roi/{id} endpoints`
7. `feat(security): filename sanitization + size/type validation`
8. `feat(frontend): minimal React+Vite upload & playback UI`
9. `chore(docker): backend & frontend Dockerfiles + compose`
10. `test: upload, roi, and validation tests`
11. `docs: README with quick-start and architecture`

---

## Step 16 — End-to-end verification

Run every check before declaring done:

1. **Unit tests:** `cd backend && pytest` → 12 passed, 0 warnings.
2. **Build & boot:** `docker compose up --build` → both services healthy, no tracebacks.
3. **Health:** `curl http://localhost:8000/health` → `{"status":"ok"}`.
4. **Swagger:** `http://localhost:8000/docs` shows three endpoints with the correct schemas.
5. **Real upload:** open `http://localhost:5173`, upload a 5–10 s MP4 with a visible face. The processed video plays back with green rectangles around the face.
6. **ROI shape:** `curl http://localhost:8000/roi/<video_id>` returns
   `{video_id, fps, frame_count, rois: [{frame_number, timestamp, x, y, width, height}, ...]}`
   sorted by `frame_number`.
7. **Bad ext:** `curl -F "file=@notes.txt" http://localhost:8000/upload` → 400.
8. **Oversize:** uploading >100 MB → 413.
9. **Unknown id:** `GET /video/nope` → 404.

If any of these fail, fix before claiming done — do not patch over with `try/except`.

---

## Anti-patterns to avoid (will fail review)

- ❌ Importing `cv2`, even transitively.
- ❌ Saving the user's filename to disk verbatim.
- ❌ Reading the whole upload into memory before validating size.
- ❌ Mid-pipeline `print` debugging left in code.
- ❌ Storing video bytes in the database (only metadata belongs in SQLite).
- ❌ Multiple-faces logic, retry loops, queue infrastructure, auth — all out of scope.
- ❌ Using `@app.on_event("startup")` (deprecated) — use `lifespan`.
- ❌ Using `datetime.utcnow()` (deprecated) — use `datetime.now(timezone.utc)`.
- ❌ Skipping the `finally: shutil.rmtree(frames_dir, ...)` cleanup — leaves orphan PNGs on every failure.
- ❌ Forgetting `-pix_fmt yuv420p` or `-movflags +faststart` on the ffmpeg encode — most browsers won't play the result.

---

## Build order summary (one line per step)

1. Empty `__init__.py` files.
2. `config.py` (env-driven paths + limits, mkdir on import).
3. `models/video.py` (Video + ROI ORM, `_utcnow`).
4. `database/session.py` (engine, `SessionLocal`, `get_db`, `init_db`).
5. `utils/filenames.py` (`sanitize_filename`).
6. `services/ffmpeg_utils.py` (`probe_fps`, `extract_frames`, `reconstruct_video`, `FFmpegError`).
7. `services/face_detector.py` (lazy mediapipe import, `FaceDetector.detect`).
8. `services/video_processor.py` (orchestrator, transactional, frames cleanup).
9. `routes/videos.py` (validate → save streamed → process → respond; FileResponse + ROI list).
10. `main.py` (lifespan + CORS + router).
11. `requirements.txt`.
12. `tests/` (conftest with env-redirect + stub, three test files).
13. Frontend (package.json, vite.config, index.html, src/, nginx.conf, styles.css).
14. Dockerfiles + `docker-compose.yml`.
15. `.gitignore` + `README.md` + commit history.
16. Run the 9 verification checks.

Stop only when **every** verification check above passes.
