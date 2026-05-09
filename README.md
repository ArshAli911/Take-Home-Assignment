# Face ROI Video API

A small containerized service that accepts an MP4 upload, detects one face per
frame with **MediaPipe**, draws a green ROI rectangle around it with **Pillow**,
re-encodes the result with **ffmpeg**, stores per-frame ROI metadata in
**SQLite**, and exposes the result through a **FastAPI** API and a minimal
**React + Vite** frontend.

> No OpenCV anywhere — frame I/O is delegated to ffmpeg, drawing to Pillow,
> detection to MediaPipe.

---

## Quick start (Docker)

```bash
docker compose up --build
```

Then open:

- **Frontend:** http://localhost:5173
- **API Swagger:** http://localhost:8000/docs

Pick a short MP4 (a 5–10 second phone clip works well), upload, and watch the
processed video play back with a green box drawn around the face.

To stop:

```bash
docker compose down            # keep data
docker compose down -v         # also drop the SQLite DB and saved videos
```

---

## Local development (without Docker)

You need Python 3.11, Node 20, and `ffmpeg` + `ffprobe` on your PATH.

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload
```

**Frontend** (separate terminal)

```bash
cd frontend
npm install
npm run dev
```

Vite serves on http://localhost:5173 and proxies `/api/*` to the backend on
`:8000`, so the same relative URLs work in dev and in Docker.

---

## API reference

| Method | Path | Body | Success | Failure |
| --- | --- | --- | --- | --- |
| `POST` | `/upload` | multipart `file=<.mp4>` | `200` `UploadResponse` | `400` bad ext · `413` >100 MB · `415` bad MIME · `500` ffmpeg failure |
| `GET` | `/video/{video_id}` | — | `200` `video/mp4` stream | `404` |
| `GET` | `/roi/{video_id}` | — | `200` `ROIResponse` | `404` |
| `GET` | `/health` | — | `200 {"status":"ok"}` | — |

**`UploadResponse`**

```json
{
  "video_id": "9f1c…",
  "original_filename": "clip.mp4",
  "frame_count": 142,
  "fps": 29.97,
  "roi_count": 138,
  "warning": null
}
```

`warning` is set to `"no faces detected"` when processing succeeds but no face
was found in any frame (the request still returns 200 — the assignment asks us
to *handle* the case, not reject the upload).

**`ROIResponse`**

```json
{
  "video_id": "9f1c…",
  "fps": 29.97,
  "frame_count": 142,
  "rois": [
    { "frame_number": 0, "timestamp": 0.0,    "x": 412, "y": 180, "width": 160, "height": 200 },
    { "frame_number": 1, "timestamp": 0.0334, "x": 414, "y": 181, "width": 160, "height": 200 }
  ]
}
```

---

## Architecture

```
┌──────────────┐  upload   ┌──────────────────────────────────┐
│  React UI    │──────────▶│  FastAPI  /upload                │
│  (Vite+nginx)│           │   ├─ validate (ext/mime/size)    │
│              │◀──────────│   ├─ save to /data/uploads       │
└──────┬───────┘  video_id │   └─ video_processor.process()   │
       │                   │         │                        │
       │  GET /video/{id}  │         ▼                        │
       │  GET /roi/{id}    │   ffmpeg extract ─► frames/      │
       ▼                   │   MediaPipe face detect          │
   <video> tag             │   Pillow draw rectangle          │
                           │   ffmpeg reconstruct ─► out.mp4  │
                           │   SQLAlchemy bulk insert ROIs    │
                           └────────────┬─────────────────────┘
                                        ▼
                                   SQLite (/data/app.db)
                                   processed mp4 (/data/processed)
```

**Pipeline (synchronous, runs inline on the request thread):**

1. `ffprobe` reads the source frame rate.
2. `ffmpeg -i input.mp4 frames/frame_%06d.png` extracts every frame.
3. For each frame: PIL → numpy → MediaPipe → bbox → `ImageDraw.rectangle` → save.
4. `ffmpeg -framerate FPS -i frames/%06d.png -c:v libx264 -pix_fmt yuv420p -movflags +faststart out.mp4` re-encodes.
5. `Video` row + bulk `ROI` rows committed in one transaction. Any exception rolls the row back and removes the partial file.
6. Frames scratch directory is wiped in `finally`.

**Separation of concerns:**

```
backend/app/
├── routes/        HTTP layer (FastAPI handlers, Pydantic models)
├── services/      Business logic (ffmpeg, face detection, pipeline)
├── models/        SQLAlchemy ORM
├── database/      Engine + session dependency
├── utils/         Small pure helpers (filename sanitization)
├── config.py      Env-driven paths and limits
└── main.py        FastAPI app wiring
```

---

## Constraints & assumptions

- **Input:** MP4 only, ≤ **100 MB**. Other formats / oversize uploads are
  rejected with 400 / 413 *before* ffmpeg runs.
- **One face per frame** — when MediaPipe returns multiple detections we keep
  the highest-confidence one.
- **Synchronous processing** — fine for short clips (a few seconds at 24–30
  fps). For longer videos a real deployment would offload to a worker; that's
  out of scope here.
- Filenames on disk are always `{uuid4}.mp4`; the user's original filename is
  sanitized and only used for display / `Content-Disposition`.

---

## Running the tests

The tests stub out the heavy processing pipeline, so they run in seconds and
don't require ffmpeg or mediapipe to be installed.

```bash
cd backend
pip install -r requirements.txt        # or just: pip install fastapi sqlalchemy pytest httpx pillow numpy python-multipart
pytest
```

Coverage:

- `test_validation.py` — filename sanitization, wrong extension (400), missing
  file (422), oversize body (413).
- `test_upload.py` — happy-path upload returns 200 + a `video_id`, processed
  download returns the MP4, unknown id 404s.
- `test_roi.py` — `/roi/{id}` returns rows in frame order with the documented
  shape, unknown id 404s.

---

## Suggested commit history

These are the commits a fresh clone of this project would naturally produce:

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

## Project layout

```
.
├── backend/
│   ├── app/
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── database/session.py
│   │   ├── models/video.py
│   │   ├── routes/videos.py
│   │   ├── services/
│   │   │   ├── ffmpeg_utils.py
│   │   │   ├── face_detector.py
│   │   │   └── video_processor.py
│   │   └── utils/filenames.py
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/{App.jsx, api.js, main.jsx, styles.css}
│   ├── nginx.conf
│   ├── vite.config.js
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```
