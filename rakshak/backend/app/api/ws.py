"""WebSocket endpoint — real-time dashboard updates for COPs.

Provides an in-memory ``ConnectionManager`` that tracks active WebSocket
connections, and a ``/ws/dashboard`` endpoint that authenticates COP users
via JWT query parameter. The ``broadcast`` function pushes messages to all
connected COPs (used by the sightings ingestion pipeline).

Keep-alive ping sent every 30 seconds.
"""

import asyncio

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.security import decode_token

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(tags=["websocket"])

logger = structlog.get_logger(__name__)

PING_INTERVAL_SECONDS = 30
ALLOWED_DASHBOARD_ROLES = ("COP", "ADMIN")
ACCESS_TOKEN_TYPE = "access"
WELCOME_MESSAGE = "Dashboard WebSocket connected"


class ConnectionManager:
    """In-memory manager for active WebSocket connections.

    Tracks COP connections and provides a ``broadcast`` method for
    pushing messages to all connected clients.
    """

    def __init__(self) -> None:
        """Initialise the connection manager with an empty connection set."""
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The incoming WebSocket connection.
        """
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("ws_connected", total=len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active set.

        Args:
            websocket: The disconnected WebSocket connection.
        """
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info("ws_disconnected", total=len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected WebSocket clients.

        Connections whose send fails are logged and removed from the pool.

        Args:
            message: Dictionary payload to send as JSON.
        """
        dead: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.debug("ws_broadcast_failed", error=str(exc))
                dead.append(connection)

        for dead_connection in dead:
            self.disconnect(dead_connection)

    @property
    def active_count(self) -> int:
        """Return the number of active WebSocket connections.

        Returns:
            int: Count of active connections.
        """
        return len(self._connections)


# Singleton connection manager — importable by the sightings API.
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_ws_token(token: str | None) -> dict | None:
    """Validate a JWT token from the WebSocket query parameter.

    Args:
        token: The raw JWT string from the ``token`` query parameter.

    Returns:
        dict | None: Decoded JWT payload if valid, None otherwise.
    """
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    if payload.get("role") not in ALLOWED_DASHBOARD_ROLES:
        return None
    return payload


async def _ping_loop(websocket: WebSocket) -> None:
    """Send keep-alive pings at regular intervals.

    Args:
        websocket: The WebSocket connection to ping.
    """
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            await websocket.send_json({"type": "ping"})
    except Exception as exc:
        logger.debug("ws_ping_loop_stopped", error=str(exc))


async def _receive_loop(websocket: WebSocket) -> None:
    """Consume inbound client frames until the socket disconnects.

    Args:
        websocket: The WebSocket connection to read from.
    """
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug("ws_message_received", data=data)
    except WebSocketDisconnect:
        logger.debug("ws_client_disconnected")


async def _serve_dashboard(websocket: WebSocket) -> None:
    """Push the welcome frame and keep the connection alive.

    Args:
        websocket: An accepted WebSocket connection.
    """
    await websocket.send_json({"type": "connected", "message": WELCOME_MESSAGE})
    ping_task = asyncio.create_task(_ping_loop(websocket))
    try:
        await _receive_loop(websocket)
    finally:
        ping_task.cancel()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.websocket("/ws/dashboard")
async def dashboard_websocket(
    websocket: WebSocket,
    token: str | None = Query(None, description="JWT access token"),
) -> None:
    """WebSocket endpoint for real-time COP dashboard updates.

    Authenticates via the ``token`` query parameter (JWT access token).
    On successful connection, sends a ``connected`` welcome message and
    starts a keep-alive ping loop. Broadcasts sighting and hotlist
    change events pushed by the ingestion pipeline.

    Args:
        websocket: The incoming WebSocket connection.
        token: JWT access token from query parameters.
    """
    claims = _validate_ws_token(token)
    if claims is None:
        await websocket.close(code=4001, reason="Invalid or missing token")
        logger.debug("ws_auth_failed")
        return

    await manager.connect(websocket)
    try:
        await _serve_dashboard(websocket)
    finally:
        manager.disconnect(websocket)
