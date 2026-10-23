"""
main.py — ClosetMate API entry point  (`uvicorn main:app`).

Order matters here: the .env file must be loaded and logging configured BEFORE
the routers/services are imported, because they read configuration at import.
"""
from settings import get_settings, load_env

load_env()
_settings = get_settings()

from logging_config import configure_logging, request_id_ctx  # noqa: E402

configure_logging(json_logs=_settings.is_prod)
_settings.validate_for_runtime()          # refuses to boot in prod without a real JWT_SECRET

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
import warnings  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from PIL import Image  # noqa: E402

from database import init_db, ping_db  # noqa: E402
from routers import auth, chat, images, recommend, skin_tone, upload, wardrobe  # noqa: E402
from security import current_user_id  # noqa: E402
from services.image_processing import prewarm_rembg  # noqa: E402

log = logging.getLogger("closetmate")

# Reject decompression-bomb images (a tiny file that expands to gigapixels). Pillow only
# *warns* between 1x and 2x the limit, so turn the warning into an error as well.
Image.MAX_IMAGE_PIXELS = _settings.max_image_pixels
warnings.simplefilter("error", Image.DecompressionBombWarning)

# Anything bigger than this is refused from the Content-Length header, before the body is read.
_MAX_BODY_BYTES = _settings.max_upload_bytes + 1024 * 1024

_REQUEST_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _clean_request_id(supplied: str | None) -> str:
    """Client-supplied ids are echoed into logs and headers: keep a safe charset and a short length."""
    cleaned = _REQUEST_ID_UNSAFE.sub("", (supplied or ""))[:64]
    return cleaned or uuid.uuid4().hex[:16]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # asyncio.to_thread uses the loop's default executor (only cpu+4 threads). Quota and
    # usage-log DB calls take milliseconds but would queue behind multi-second image jobs
    # on that small pool, so give the loop a larger one.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=32, thread_name_prefix="cm-worker")
    )
    # Load the background-removal model off the request path so the first user
    # doesn't pay for it. Skipped under test.
    if _settings.env != "test":
        threading.Thread(target=prewarm_rembg, name="rembg-prewarm", daemon=True).start()
    yield


app = FastAPI(
    title="ClosetMate AI Backend",
    description="AI-powered wardrobe management and outfit recommendation API",
    version="0.2.0",
    lifespan=lifespan,
    # Interactive docs are a dev convenience, not something to publish.
    docs_url=None if _settings.is_prod else "/docs",
    redoc_url=None,
    openapi_url=None if _settings.is_prod else "/openapi.json",
)


# ---------------------------------------------------------------------------
# Request id + access log + basic hardening headers
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = _clean_request_id(request.headers.get("x-request-id"))
    request.state.request_id = rid
    token = request_id_ctx.set(rid)
    started = time.perf_counter()
    status_code = 500
    try:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
            status_code = 413
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
                headers={"X-Request-ID": rid},
            )

        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if not request.url.path.startswith("/uploads"):
            response.headers.setdefault("Cache-Control", "no-store")   # API responses are per-user
        if _settings.is_prod:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        level = logging.DEBUG if request.url.path in ("/health", "/ready") else logging.INFO
        log.log(level, "%s %s -> %s %dms", request.method, request.url.path, status_code, elapsed_ms)
        request_id_ctx.reset(token)


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Log the full traceback server-side; never ship it to the client in production."""
    rid = getattr(request.state, "request_id", None)
    # This handler runs in Starlette's outermost middleware, after request_context has already
    # reset the logging context — put the id back so the traceback is searchable by request.
    request_id_ctx.set(rid or "-")
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    body = {"detail": "Internal server error", "request_id": rid}
    if _settings.expose_error_details:
        body["error"] = f"{type(exc).__name__}: {exc}"
    return JSONResponse(status_code=500, content=body, headers={"X-Request-ID": rid or "-"})


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """FastAPI's default 422 body echoes the submitted value (`input`) — for /auth that is the password."""
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


# ---------------------------------------------------------------------------
# CORS — the mobile app doesn't need it (no browser). Web clients get an explicit
# allow-list in production via CORS_ORIGINS; dev defaults to "*".
# ---------------------------------------------------------------------------
if _settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Ensure database schema exists (idempotent).
init_db()


# ---------------------------------------------------------------------------
# Routers. Everything except sign-up/sign-in and the pre-registration selfie scan
# requires a valid access token; the per-route handlers additionally check that
# any user_id in the path/body is the caller's own.
# ---------------------------------------------------------------------------
_authed = [Depends(current_user_id)]

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"], dependencies=_authed)
app.include_router(wardrobe.router, prefix="/wardrobe", tags=["Wardrobe"], dependencies=_authed)
app.include_router(recommend.router, prefix="/recommend", tags=["Recommend"], dependencies=_authed)
app.include_router(chat.router, prefix="/chat", tags=["Chat"], dependencies=_authed)
app.include_router(images.router, prefix="/images", tags=["Images"], dependencies=_authed)
# Root-level aliases: older app builds call /remove-bg directly.
app.include_router(images.router, prefix="", tags=["Images (root aliases)"], dependencies=_authed)
# Public by design: used during registration, before an account exists (IP rate-limited).
app.include_router(skin_tone.router, prefix="", tags=["Skin Tone"])

# Locally-stored processed images: a dev/fallback convenience. Once production stores
# images in GCS there is nothing to serve from disk, so the mount is not exposed at all.
if not (_settings.is_prod and os.getenv("GCS_BUCKET")):
    _uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(_uploads_dir, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"message": "ClosetMate Backend Running"}


@app.get("/health")
def health():
    """Liveness: the process is up. Deliberately does NOT touch the database, so an
    uptime monitor pinging it every minute can't keep a scale-to-zero Postgres awake."""
    return {"status": "ok", "version": app.version}


@app.get("/ready")
def ready():
    """Readiness: the database is reachable. Use for deploy checks, not frequent pings."""
    try:
        ping_db()
    except Exception:  # noqa: BLE001
        log.exception("readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}
