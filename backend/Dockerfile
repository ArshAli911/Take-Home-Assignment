FROM python:3.11-slim

# ffmpeg/ffprobe for video I/O. libgl1/libglib2.0-0 are required by the
# mediapipe wheels at import time even though we never call cv2.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so they cache when only app code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
