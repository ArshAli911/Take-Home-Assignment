"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.session import init_db
from app.routes.videos import router as videos_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create tables on startup. Nothing to tear down on shutdown.
    init_db()
    yield


app = FastAPI(title="Face ROI Video API", version="1.0.0", lifespan=lifespan)

# CORS is mostly belt-and-suspenders: in Docker the frontend nginx
# proxies /api/* to us same-origin, and the Vite dev server proxies too.
# Allowing localhost makes ad-hoc curl/Postman testing painless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:5173",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(videos_router)
