"""Notification service — push dashboard events to connected COPs.

Builds the WebSocket payloads for new sightings and hotlist changes and
delivers them through the in-process connection registry declared in
``app.api.ws``. Asynchronous endpoints await the ``push_*`` helpers directly;
synchronous endpoints and background jobs use :func:`schedule`, which hands
the coroutine to the event loop captured at application startup.
"""

import asyncio
from typing import Any, Coroutine

import structlog

from app.api.ws import manager
from app.models.hotlist import Hotlist
from app.models.sighting import Sighting

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

EVENT_NEW_SIGHTING = "new_sighting"
EVENT_HOTLIST_CHANGE = "hotlist_change"

_event_loop: asyncio.AbstractEventLoop | None = None

# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def sighting_payload(sighting: Sighting, plate: str) -> dict:
    """Build the dashboard payload for a new sighting.

    Args:
        sighting: The committed sighting row.
        plate: The matched (hotlisted) plate.

    Returns:
        dict: Sighting summary used by the dashboard toast, map and table.
    """
    return {
        "sighting_id": str(sighting.id),
        "hotlist_id": str(sighting.hotlist_id),
        "plate": plate,
        "lat": sighting.lat,
        "lng": sighting.lng,
        "captured_at": sighting.captured_at.isoformat(),
        "confidence": sighting.confidence,
        "photo_url": sighting.photo_url,
    }


def hotlist_payload(entry: Hotlist) -> dict:
    """Build the dashboard payload for a hotlist status change.

    Args:
        entry: The hotlist entry whose state changed.

    Returns:
        dict: Hotlist summary used by the dashboard toast.
    """
    return {
        "hotlist_id": str(entry.id),
        "plate": entry.plate,
        "status": entry.status.value,
        "fir_ref": entry.fir_ref,
        "recovered_at": (
            entry.recovered_at.isoformat() if entry.recovered_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------


async def push_new_sighting(payload: dict) -> None:
    """Broadcast a new-sighting event to every connected dashboard.

    Args:
        payload: Payload built by :func:`sighting_payload`.

    Returns:
        None.
    """
    await manager.broadcast({"type": EVENT_NEW_SIGHTING, "data": payload})


async def push_hotlist_change(payload: dict) -> None:
    """Broadcast a hotlist-change event to every connected dashboard.

    Args:
        payload: Payload built by :func:`hotlist_payload`.

    Returns:
        None.
    """
    await manager.broadcast({"type": EVENT_HOTLIST_CHANGE, "data": payload})


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Remember the application event loop used by :func:`schedule`.

    Args:
        loop: The running loop captured during application startup.

    Returns:
        None.
    """
    global _event_loop
    _event_loop = loop
    logger.info("notifier_event_loop_bound")


def schedule(coroutine: Coroutine[Any, Any, None]) -> None:
    """Run a broadcast coroutine from synchronous request code.

    When no loop is bound (for example under the test ASGI transport, which
    does not run the lifespan) the coroutine is closed and the event is
    dropped with a debug log rather than left un-awaited.

    Args:
        coroutine: Coroutine returned by a ``push_*`` helper.

    Returns:
        None.
    """
    if _event_loop is None or _event_loop.is_closed():
        logger.debug("notify_skipped", reason="event loop not bound")
        coroutine.close()
        return
    asyncio.run_coroutine_threadsafe(coroutine, _event_loop)
