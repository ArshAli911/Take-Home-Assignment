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

![Face ROI Video API architecture](face_roi_video_api_architecture.svg)

```
┌──────────────┐  POST /upload (mp4)   ┌────────────────────────────────────────┐
│  React UI    │──────────────────────▶│  FastAPI  routes/videos.py             │
│  (Vite+nginx)│                       │   ├─ validate ext / mime               │
│              │◀──────────────────────│   ├─ stream-save with size cap (413)   │
└──────┬───────┘  UploadResponse JSON  │   └─ video_processor.process_video()   │
       │                               └─────────────────┬──────────────────────┘
       │  GET /video/{id}                                │
       │  GET /roi/{id}                                  ▼
       ▼                               ┌────────────────────────────────────────┐
   <video> tag                         │  Processing pipeline (synchronous)     │
   <ul> meta panel                     │  1. ffprobe → fps                      │
                                       │  2. ffmpeg → frames/frame_%06d.png     │
                                       │  3. for each frame:                    │
                                       │       PIL.open → numpy RGB             │
                                       │       FaceDetector.detect:             │
                                       │         ├─ MediaPipe short-range (0)   │
                                       │         └─ fallback: full-range (1)    │
                                       │       _clamp_bbox(...)                 │
                                       │         (trims overflow when face is   │
                                       │          too close to camera)          │
                                       │       ImageDraw.rectangle (lime, 3px)  │
                                       │       img.save (overwrite)             │
                                       │  4. ffmpeg → out.mp4                   │
                                       │       (-c:v libx264 -pix_fmt yuv420p   │
                                       │        -movflags +faststart)           │
                                       │  5. INSERT Video + bulk ROI in one txn │
                                       │  6. finally: rmtree frames/{video_id}  │
                                       └─────────────────┬──────────────────────┘
                                                         ▼
                                       SQLite      /data/app.db    (metadata)
                                       Disk        /data/processed (mp4 output)
                                       Disk        /data/uploads   (raw input)
```

**Pipeline notes:**

1. **Probe** — `ffprobe -select_streams v:0 -show_entries stream=r_frame_rate`. Output is parsed as a rational; falls back to 30 fps on parse error.
2. **Extract** — `ffmpeg -i input.mp4 -start_number 0 frames/frame_%06d.png`. Six-digit zero-padding so lexical sort matches frame order.
3. **Detect → clamp → draw** — short-range model first because it's the one that recognizes faces filling most of the frame (close-to-camera). If both detectors miss, the frame is left untouched and no ROI row is inserted. If a bbox is returned but extends past the frame edges, `_clamp_bbox` trims it to the visible region rather than discarding it.
4. **Re-encode** — `-pix_fmt yuv420p` for browser compatibility; `-movflags +faststart` so playback starts before the file is fully buffered.
5. **Persist** — single transaction: `Video` row first (so the FK is valid), then `bulk_save_objects([ROI ...])`. Any exception inside the pipeline rolls the row back and removes a half-written `out.mp4` from disk.
6. **Cleanup** — `shutil.rmtree(frames_dir, ignore_errors=True)` in `finally` so the scratch dir never leaks, even on ffmpeg failure.

**Separation of concerns:**

```
backend/app/
├── routes/        HTTP layer — FastAPI handlers + Pydantic models, no
│                  business logic beyond input validation and 4xx mapping.
├── services/      Business logic
│   ├── ffmpeg_utils.py      probe_fps, extract_frames, reconstruct_video
│   ├── face_detector.py     MediaPipe wrapper + _clamp_bbox helper
│   └── video_processor.py   end-to-end orchestrator (transactional)
├── models/        SQLAlchemy ORM (Video, ROI)
├── database/      Engine + SessionLocal + get_db dependency
├── utils/         Small pure helpers (filename sanitization)
├── config.py      Env-driven paths and limits
└── main.py        FastAPI app wiring (lifespan, CORS, router)
```

**Frontend / nginx:**

```
browser ──/api/*─▶ nginx (port 80, frontend container)
                     │   client_max_body_size 110M
                     │   strip /api prefix on proxy_pass
                     ▼
               backend (port 8000, FastAPI)
```

In dev (`npm run dev`), Vite's dev server replaces nginx and proxies the same `/api/*` prefix to `localhost:8000`, so URLs are identical in dev and prod.

---

## Code design

The codebase is small on purpose. The design choices below are the ones that
materially shape how the code behaves under load, on failure, and during
change — not stylistic preferences.

### Layered, one-way dependencies

```
routes/  ─▶  services/  ─▶  models/  +  database/
              │
              └─▶  utils/   (pure helpers, no I/O)
```

Routes know about HTTP (status codes, multipart, Pydantic schemas) and nothing
about ffmpeg or MediaPipe. Services know about the pipeline and the ORM but
never about `Request`/`Response`. This is what keeps `video_processor.process_video`
testable without a TestClient and what lets the route layer stay a thin
adapter — input validation, error mapping, and delegation. Each layer imports
only from layers below it; there are no cycles.

### FastAPI dependency injection for sessions

`get_db` is the single seam through which a request acquires a SQLAlchemy
session. Doing it as a FastAPI dependency (rather than constructing a session
inside the route) gives three things for free: (1) per-request lifecycle —
one session opened, one closed, no leaks; (2) trivial test override via
`app.dependency_overrides[get_db]`; (3) a natural place to add rollback-on-
exception without touching any handler. Services receive the session as a
parameter, never reach for a global.

### Synchronous pipeline, transactional boundary

`process_video` runs inline on the request thread. The assignment is bounded
(≤100 MB, short clips), so the simplest correct thing is also the right thing —
no Celery, no Redis, no task table to keep consistent with disk. The trade-off
is explicit in code: the function takes a `db: Session`, does the full
extract → detect → annotate → reconstruct → persist sequence, and either
commits one atomic transaction or rolls it back *and* removes the half-written
`out.mp4`. There is no state where the DB and the filesystem disagree about
whether a video exists. When this needs to scale, the seam to move it behind a
worker is exactly one function call in `routes/videos.py`.

### Resource lifecycle is enforced, not hoped for

Every owned resource is released by a `with`/`try-finally` rather than relying
on GC:

- `Image.open(...) as img` — PIL file handles closed promptly even on the
  thousands of frames a video produces.
- `FaceDetector.close()` in `_annotate_frames`'s `finally` — MediaPipe holds
  native graph resources that don't get cleaned up by `__del__` reliably.
- `shutil.rmtree(frames_dir, ignore_errors=True)` in `finally` — the scratch
  directory never leaks, even when ffmpeg fails mid-reconstruct.

This matters because the failure modes are real: a malformed frame, an OOM
mid-pipeline, an ffmpeg timeout. The cleanup contract holds in all of them.

### Errors fail loudly at the boundary, not silently in the middle

Services raise typed exceptions (`FFmpegError`, SQLAlchemy errors, plain
`ValueError` for sanitization). The route layer is the only place that maps
exceptions to HTTP status codes — 400 for bad input, 413 for oversize, 415 for
wrong MIME, 500 for downstream tool failure. Inside services, "no face
detected on this frame" is an expected outcome (the row is just omitted),
while "ffmpeg returned non-zero" is an exception. That split keeps the happy
path readable and the error path explicit.

### Configuration is environment-driven, with safe defaults

`config.py` reads paths and limits from env vars (`DATA_DIR`, `MAX_UPLOAD_MB`)
and falls back to sensible defaults for local dev. Nothing in the code hard-
codes `/data/uploads` or `100 * 1024 * 1024` — the same image runs locally,
in compose, and (with one env change) against a mounted volume in production.
The Vite/nginx side mirrors the same idea: `/api/*` is the only path the
frontend knows, and *where* it lands is a deploy-time concern.

### Logging is structured around the unit of work

Every pipeline log line carries `video_id=…` so a failed upload can be
reconstructed from logs alone — probe → extract → annotate → reconstruct →
persist, with counts at each step. The detector logs detection rate
(`X faces across Y frames`), which is the metric most likely to drift
silently when a model or threshold changes.

### Tests stub the heavy edges, exercise the seams

The tests don't need ffmpeg, MediaPipe, or a real video. They override
`get_db` with an in-memory SQLite session, monkeypatch `process_video` to
a deterministic stub, and POST real multipart bodies through `TestClient`.
That's deliberate: the things worth testing fast are the contracts
(validation, status codes, response shapes, ROI ordering, bbox clamping
math), not the third-party tools. Integration with the real tools is
verified by running the service end-to-end against a sample clip — once,
manually — which is the right cost/value trade-off for a project this size.

---

## Constraints & assumptions

- **Input:** MP4 only, ≤ **100 MB**. Other formats / oversize uploads are
  rejected with 400 / 413 *before* ffmpeg runs.
- **One face per frame** — when MediaPipe returns multiple detections we keep
  the highest-confidence one.
- **Face too close to camera** — the detector tries the short-range MediaPipe
  model first (tuned for selfies, < 2 m) and falls back to the full-range model
  (< 5 m), so close-up footage isn't silently missed. If the returned bbox
  extends past the frame edges (common when the face fills most of the view),
  the box is *trimmed* to the visible region rather than discarded — the user
  still sees a rectangle around whatever part of the face is on-screen.
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
- `test_face_detector.py` — bbox clamping for normal faces, faces overflowing
  the right/bottom edges, faces overflowing the top/left edges (the
  "too close to camera" case), fully off-screen, and zero-sized bboxes.

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
