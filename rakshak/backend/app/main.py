"""FastAPI application entry-point for RAKSHAK.

Defines the app with lifespan management, CORS middleware,
global exception handling, the health-check endpoint at GET /api/v1/healthz,
the local photo mount, and includes the v1 API router.
"""

import asyncio
import structlog
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.exceptions import AppError, InvalidStateTransition, error_response

from app.api.auth import router as auth_router
from app.api.complaints import router as complaints_router
from app.api.hotlist import router as hotlist_router
from app.api.devices import router as devices_router
from app.api.sightings import router as sightings_router
from app.api.analytics import router as analytics_router
from app.api.admin import router as admin_router
from app.api.detect import router as detect_router
from app.api.ws import router as ws_router
from app.services import notifier
from app.services.scheduler import create_scheduler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

APP_VERSION = "0.1.0"
API_V1_PREFIX = "/api/v1"
PHOTO_SUBDIR = "sightings"
LOCAL_STORAGE_BACKEND = "local"


def _mount_photo_store(application: FastAPI) -> None:
    """Serve stored sighting photos when the local storage backend is active.

    ``photo_url`` values returned by the API are relative paths such as
    ``/sightings/<uuid>.jpg``; this mount makes them resolvable. Remote
    backends (S3/MinIO) serve their own URLs and need no mount.

    Args:
        application: The FastAPI application instance.

    Returns:
        None.
    """
    if settings.STORAGE_BACKEND.lower() != LOCAL_STORAGE_BACKEND:
        return

    photo_dir = Path(settings.UPLOAD_DIR) / PHOTO_SUBDIR
    try:
        photo_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.warning(
            "photo_store_mount_skipped",
            path=str(photo_dir),
            error=str(error),
        )
        return

    application.mount(
        f"/{PHOTO_SUBDIR}",
        StaticFiles(directory=str(photo_dir)),
        name=PHOTO_SUBDIR,
    )


def _is_sightings_or_detect_path(request_url: str) -> bool:
    """Check if a request originated from a sightings or detect path.

    Used to sanitise plate values from error logs for privacy.

    Args:
        request_url: The request URL path.

    Returns:
        bool: True if the path is sightings or detect.
    """
    return "/sightings" in request_url or "/detect" in request_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle.

    Starts the APScheduler for FIR expiry and nightly purge jobs on
    startup, and shuts it down cleanly on application shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        None — control returns to FastAPI after startup.
    """
    notifier.bind_event_loop(asyncio.get_running_loop())
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("rakshak_startup", version=APP_VERSION, scheduler_started=True)

    yield

    scheduler.shutdown(wait=False)
    logger.info("rakshak_shutdown")


app = FastAPI(
    title="RAKSHAK",
    description="Privacy-first mobile ANPR network for stolen vehicle detection",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle typed application errors with the standard error shape.

    Args:
        request: The incoming HTTP request.
        exc: The application error.

    Returns:
        JSONResponse: Standard error response with appropriate status code.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.code, exc.message, exc.field),
    )


@app.exception_handler(InvalidStateTransition)
async def invalid_state_transition_handler(
    request: Request, exc: InvalidStateTransition
) -> JSONResponse:
    """Handle illegal hotlist state transitions with 409.

    Args:
        request: The incoming HTTP request.
        exc: The state transition error.

    Returns:
        JSONResponse: 409 with INVALID_TRANSITION code.
    """
    return JSONResponse(
        status_code=409,
        content=error_response(
            "INVALID_TRANSITION",
            f"Cannot transition from {exc.from_state} to {exc.to_state}",
        ),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Returns the standard error shape with INTERNAL_ERROR code.
    Logs the full traceback via structlog but sanitises plate values
    and tokens for sightings/detect paths (privacy invariant).

    Args:
        request: The incoming HTTP request.
        exc: The unhandled exception.

    Returns:
        JSONResponse: 500 with INTERNAL_ERROR code.
    """
    sanitize = _is_sightings_or_detect_path(str(request.url))
    log_kwargs: dict = {"path": str(request.url.path)}
    if not sanitize:
        log_kwargs["exc_info"] = exc
    logger.error("unhandled_exception", **log_kwargs)
    return JSONResponse(
        status_code=500,
        content=error_response("INTERNAL_ERROR", "An internal error occurred"),
    )


@app.get(f"{API_V1_PREFIX}/healthz")
async def health_check() -> dict[str, str]:
    """Return service health status.

    Returns:
        dict: A dictionary containing status and version.
    """
    return {"status": "ok", "version": APP_VERSION}


app.include_router(auth_router, prefix=API_V1_PREFIX)
app.include_router(complaints_router, prefix=API_V1_PREFIX)
app.include_router(hotlist_router, prefix=API_V1_PREFIX)
app.include_router(devices_router, prefix=API_V1_PREFIX)
app.include_router(sightings_router, prefix=API_V1_PREFIX)
app.include_router(analytics_router, prefix=API_V1_PREFIX)
app.include_router(admin_router, prefix=API_V1_PREFIX)
app.include_router(detect_router, prefix=API_V1_PREFIX)
app.include_router(ws_router, prefix=API_V1_PREFIX)
_mount_photo_store(app)
