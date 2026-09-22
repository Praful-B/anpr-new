"""Device simulator — offline ANPR detection pipeline for demo and testing.

Simulates the on-device detection flow described in §7 Flow C of
PROJECT_INFO.md: frame grab → quality filter → YOLO plate detection →
OCR → Indian plate normalisation → temporal voting → hotlist matching →
hit event batching and POST to /api/v1/sightings.

The simulator can optionally register a device at startup if no
--device-token is provided (requires --device-email + --device-password).

Offline hits are queued to a local SQLite database and flushed on
reconnection.

Usage:
    python scripts/device_simulator.py \\
        --video /data/samples/sample1.mp4 \\
        --plate MH12AB1234 \\
        --device-email volunteer@rakshak.local \\
        --device-password Vol@12345
"""

import argparse
import base64
import os
import re
import sqlite3
import sys
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
import requests
import structlog

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAME_INTERVAL_MS = 33
BLUR_THRESHOLD = 80.0
BRIGHTNESS_THRESHOLD = 40.0
TEMPORAL_WINDOW = 5
TEMPORAL_MIN_AGREEMENT = 3
FLUSH_INTERVAL_SECONDS = 5.0
PLATE_CONFIDENCE_THRESHOLD = 0.3
MAX_PHOTO_DIMENSION = 1280
JPEG_QUALITY = 70
DEFAULT_LAT = 19.0760
DEFAULT_LNG = 72.8777
OFFLINE_DB_PATH = "device_simulator_queue.db"
BACKEND_URL_ENV_VAR = "RAKSHAK_BACKEND_URL"
DEFAULT_BACKEND_URL = os.environ.get(BACKEND_URL_ENV_VAR, "http://localhost:8000")
YOLO_WEIGHTS = "yolo11n.pt"
OCR_LANGUAGES = ["en"]
REQUEST_TIMEOUT_SECONDS = 10
MAX_LOG_BODY_CHARS = 300
VOLUNTEER_DEVICE_TYPE = "VOLUNTEER"
SIGHTINGS_PATH = "/api/v1/sightings/"
LOGIN_PATH = "/api/v1/auth/login"
DEVICE_REGISTER_PATH = "/api/v1/devices/register"

logger = structlog.get_logger("device_simulator")


# ---------------------------------------------------------------------------
# Offline queue (SQLite)
# ---------------------------------------------------------------------------


def init_offline_db(db_path: str) -> sqlite3.Connection:
    """Initialise the offline SQLite queue for hit events.

    Creates the ``pending_hits`` table if it does not already exist.

    Args:
        db_path: Filesystem path for the SQLite database.

    Returns:
        sqlite3.Connection: Connection to the SQLite database.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_hits (
            id TEXT PRIMARY KEY,
            plate TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            captured_at TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            photo_b64 TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def queue_hit(
    conn: sqlite3.Connection,
    plate: str,
    lat: float,
    lng: float,
    captured_at: str,
    confidence: int,
    photo_b64: str,
) -> None:
    """Insert a hit event into the offline SQLite queue.

    Args:
        conn: SQLite connection.
        plate: Normalised plate string.
        lat: Latitude of detection.
        lng: Longitude of detection.
        captured_at: ISO-8601 UTC timestamp.
        confidence: OCR confidence (0-100).
        photo_b64: Base64-encoded JPEG photo.
    """
    conn.execute(
        """
        INSERT INTO pending_hits (id, plate, lat, lng, captured_at, confidence, photo_b64, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            plate,
            lat,
            lng,
            captured_at,
            confidence,
            photo_b64,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def _row_to_hit_event(row: tuple) -> dict:
    """Convert a queued SQLite row into a sighting event payload.

    Args:
        row: ``(id, plate, lat, lng, captured_at, confidence, photo_b64)``.

    Returns:
        dict: Event dictionary ready to POST to the sightings endpoint.
    """
    _, plate, lat, lng, captured_at, confidence, photo_b64 = row
    return {
        "plate": plate,
        "lat": lat,
        "lng": lng,
        "captured_at": captured_at,
        "confidence": confidence,
        "photo_b64": photo_b64,
    }


def _send_hit(
    backend_url: str,
    device_token: str,
    hit_id: str,
    event: dict,
) -> bool:
    """POST a single queued hit to the backend.

    Args:
        backend_url: Base URL of the RAKSHAK backend.
        device_token: Device authentication token.
        hit_id: Row id, used for log correlation.
        event: The sighting event payload.

    Returns:
        bool: True when the backend accepted the hit.
    """
    headers = {"X-Device-Token": device_token, "Content-Type": "application/json"}
    try:
        response = requests.post(
            f"{backend_url}{SIGHTINGS_PATH}",
            json={"events": [event]},
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("flush_error", hit_id=hit_id, error=str(exc))
        return False

    if response.status_code == 200:
        return True

    logger.warning(
        "flush_drop",
        hit_id=hit_id,
        status=response.status_code,
        body=response.text[:MAX_LOG_BODY_CHARS],
    )
    return False


def flush_queue(
    conn: sqlite3.Connection,
    backend_url: str,
    device_token: str,
) -> int:
    """Flush all pending hits from the SQLite queue to the backend.

    Sends each hit as a single-event batch. On success, deletes the row.
    On failure, logs a warning and leaves the row for the next flush.

    Args:
        conn: SQLite connection.
        backend_url: Base URL of the RAKSHAK backend.
        device_token: Device authentication token.

    Returns:
        int: Number of hits successfully flushed.
    """
    rows = conn.execute(
        "SELECT id, plate, lat, lng, captured_at, confidence, photo_b64"
        " FROM pending_hits ORDER BY created_at"
    ).fetchall()

    flushed = 0
    for row in rows:
        if not _send_hit(backend_url, device_token, row[0], _row_to_hit_event(row)):
            continue
        conn.execute("DELETE FROM pending_hits WHERE id = ?", (row[0],))
        conn.commit()
        flushed += 1

    return flushed


# ---------------------------------------------------------------------------
# Device registration & authentication
# ---------------------------------------------------------------------------


def register_device(
    backend_url: str,
    email: str,
    password: str,
) -> tuple[str, str]:
    """Authenticate a user and register a new device.

    Steps:
        1. POST /auth/login to obtain an access token.
        2. POST /devices/register to obtain device_id and device_token.

    Args:
        backend_url: Base URL of the RAKSHAK backend.
        email: User email for authentication.
        password: User password for authentication.

    Returns:
        tuple[str, str]: (device_id, device_token)

    Raises:
        SystemExit: If authentication or registration fails.
    """
    logger.info("authenticating", email=email)
    login_resp = requests.post(
        f"{backend_url}{LOGIN_PATH}",
        json={"email": email, "password": password},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if login_resp.status_code != 200:
        logger.error(
            "login_failed",
            status=login_resp.status_code,
            body=login_resp.text[:MAX_LOG_BODY_CHARS],
        )
        sys.exit(1)

    access_token = login_resp.json()["access_token"]
    logger.info("registering_device")

    register_resp = requests.post(
        f"{backend_url}{DEVICE_REGISTER_PATH}",
        json={"type": VOLUNTEER_DEVICE_TYPE},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if register_resp.status_code != 201:
        logger.error(
            "register_failed",
            status=register_resp.status_code,
            body=register_resp.text[:MAX_LOG_BODY_CHARS],
        )
        sys.exit(1)

    data = register_resp.json()
    device_id = data["device_id"]
    device_token = data["device_token"]
    logger.info("device_registered", device_id=device_id)
    return device_id, device_token


# ---------------------------------------------------------------------------
# Frame quality filtering
# ---------------------------------------------------------------------------


def is_frame_usable(frame: np.ndarray) -> bool:
    """Check whether a frame passes blur and brightness quality checks.

    Rejects frames where the Laplacian variance (blur metric) is below
    BLUR_THRESHOLD or the mean brightness is below BRIGHTNESS_THRESHOLD.

    Args:
        frame: BGR image as a numpy array.

    Returns:
        bool: True if the frame is sharp and bright enough.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < BLUR_THRESHOLD:
        return False

    mean_brightness = float(np.mean(gray))
    return mean_brightness >= BRIGHTNESS_THRESHOLD


# ---------------------------------------------------------------------------
# Plate detection and OCR
# ---------------------------------------------------------------------------


def detect_plates(
    frame: np.ndarray,
    yolo_model: Any,
) -> list[np.ndarray]:
    """Run YOLO inference to detect licence plate regions.

    Uses the pretrained YOLO11n model as a stand-in. Filters detections
    by confidence threshold.

    Args:
        frame: BGR image as a numpy array.
        yolo_model: Loaded ultralytics YOLO model.

    Returns:
        list[np.ndarray]: List of cropped plate images (BGR).
    """
    results = yolo_model(frame, verbose=False)
    plates = []

    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            if conf < PLATE_CONFIDENCE_THRESHOLD:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            plate_crop = frame[y1:y2, x1:x2]
            if plate_crop.size == 0:
                continue
            plates.append(plate_crop)

    return plates


def ocr_plate(plate_crop: np.ndarray, reader: Any) -> tuple[str, int]:
    """Perform OCR on a cropped plate image using EasyOCR.

    Args:
        plate_crop: Cropped BGR image of a licence plate.
        reader: Loaded EasyOCR Reader instance.

    Returns:
        tuple[str, int]: (raw OCR text, confidence score 0-100).
    """
    rgb_crop = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2RGB)
    detections = reader.readtext(rgb_crop)

    if not detections:
        return "", 0

    texts = []
    total_conf = 0.0
    for _, text, conf in detections:
        texts.append(text.strip())
        total_conf += conf

    raw_text = " ".join(texts)
    avg_conf = int(total_conf / len(detections) * 100) if detections else 0
    return raw_text, min(avg_conf, 100)


# ---------------------------------------------------------------------------
# Indian plate normalisation (§8)
# ---------------------------------------------------------------------------

MIN_PLATE_LENGTH = 6
DIGIT_CORRECTIONS = {"O": "0", "I": "1", "B": "8", "S": "5", "Z": "2"}
ALPHA_CORRECTIONS = {"0": "O", "1": "I"}

PLATE_STRIP_RE = re.compile(r"[\s\-]")
INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")


def normalise_plate(raw_plate: str) -> str:
    """Normalise a raw OCR plate string to the canonical Indian format.

    Implements §8 of PROJECT_INFO.md:
    1. Uppercase, strip spaces/hyphens.
    2. Positional OCR character correction.
    3. Validate against Indian plate pattern.

    Args:
        raw_plate: The raw plate string from OCR.

    Returns:
        str: The normalised plate string, or empty string if invalid.
    """
    if not raw_plate or not raw_plate.strip():
        return ""

    normalised = PLATE_STRIP_RE.sub("", raw_plate.upper())
    return _apply_positional_corrections(normalised)


def _apply_positional_corrections(plate: str) -> str:
    """Apply positional OCR corrections based on Indian plate structure.

    Args:
        plate: Uppercased plate string with spaces/hyphens removed.

    Returns:
        str: Plate with positional OCR corrections applied.
    """
    if INDIAN_PLATE_RE.match(plate):
        return plate

    chars = list(plate)
    if len(chars) < MIN_PLATE_LENGTH:
        return plate

    structure = _infer_plate_structure(chars)
    for index, char_type in enumerate(structure[: len(chars)]):
        chars[index] = _correct_character(chars[index], char_type)

    return "".join(chars)


def _correct_character(character: str, expected_type: str) -> str:
    """Correct a single OCR character given its expected type.

    Args:
        character: The character read by OCR.
        expected_type: One of ``alpha``, ``digit`` or ``unknown``.

    Returns:
        str: The corrected character, or the input when no rule applies.
    """
    if expected_type == "digit" and character in DIGIT_CORRECTIONS:
        return DIGIT_CORRECTIONS[character]
    if expected_type == "alpha" and character in ALPHA_CORRECTIONS:
        return ALPHA_CORRECTIONS[character]
    return character


def _infer_plate_structure(chars: list[str]) -> list[str]:
    """Infer the expected character type at each position.

    Uses the Indian plate structure: 2 alpha + 1-2 digits + 1-3 alpha + 4 digits.

    Args:
        chars: List of characters from the normalised plate.

    Returns:
        list[str]: List of ``"digit"`` or ``"alpha"`` strings.
    """
    total = len(chars)
    structure: list[str] = ["alpha", "alpha"] + ["unknown"] * max(0, total - 2)

    rto_end = _find_rto_end(chars)
    series_start = rto_end
    series_end = _find_series_end(chars, series_start)

    for i in range(series_start, min(series_end, total)):
        structure[i] = "alpha"
    for i in range(series_end, total):
        structure[i] = "digit"
    for i in range(2, series_start):
        structure[i] = "digit"

    return structure


def _find_rto_end(chars: list[str]) -> int:
    """Find where the RTO digit code ends."""
    for i in range(2, len(chars)):
        if chars[i].isalpha():
            return i
    return min(4, len(chars))


def _find_series_end(chars: list[str], series_start: int) -> int:
    """Find where the alpha series code ends."""
    for i in range(series_start, len(chars)):
        if chars[i].isdigit():
            return i
    return max(0, len(chars) - 4)


# ---------------------------------------------------------------------------
# Temporal voting
# ---------------------------------------------------------------------------


class TemporalVoter:
    """Maintains a sliding window of recent OCR reads per tracker ID.

    Accepts a plate when at least TEMPORAL_MIN_AGREEMENT out of the last
    TEMPORAL_WINDOW reads agree on the same normalised string.
    """

    def __init__(self) -> None:
        """Initialise the temporal voter."""
        self._windows: dict[int, deque[str]] = {}

    def vote(self, tracker_id: int, normalised_plate: str) -> str | None:
        """Record a read and return the agreed plate if threshold met.

        Args:
            tracker_id: Numeric tracker ID for the detected plate region.
            normalised_plate: Normalised plate string from this frame.

        Returns:
            str | None: The agreed plate string if threshold met, else None.
        """
        if tracker_id not in self._windows:
            self._windows[tracker_id] = deque(maxlen=TEMPORAL_WINDOW)

        self._windows[tracker_id].append(normalised_plate)

        for plate, count in Counter(self._windows[tracker_id]).items():
            if count >= TEMPORAL_MIN_AGREEMENT:
                return plate

        return None


# ---------------------------------------------------------------------------
# Photo encoding
# ---------------------------------------------------------------------------


def encode_frame_jpeg(frame: np.ndarray) -> str:
    """Encode a frame as a base64 JPEG string.

    Resizes to MAX_PHOTO_DIMENSION on the longest side and compresses
    at JPEG_QUALITY.

    Args:
        frame: BGR image as a numpy array.

    Returns:
        str: Base64-encoded JPEG string.
    """
    h, w = frame.shape[:2]
    scale = min(MAX_PHOTO_DIMENSION / max(h, w), 1.0)
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

    success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not success:
        return ""

    return base64.b64encode(buffer.tobytes()).decode("ascii")


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------


@dataclass
class SimulationStats:
    """Mutable counters tracked across a single simulation run.

    Attributes:
        frame_number: Frames read from the video so far.
        detection_count: Plates that passed OCR and normalisation.
        match_count: Detections whose plate matched the target plate.
        sent_count: Hit events successfully flushed to the backend.
    """

    frame_number: int = 0
    detection_count: int = 0
    match_count: int = 0
    sent_count: int = 0


@dataclass
class SimulationContext:
    """Immutable-ish shared state for one device-simulation run.

    Attributes:
        args: Parsed command-line arguments.
        device_token: Token used to authenticate hit ingestion.
        yolo_model: Loaded ultralytics YOLO model.
        reader: Loaded EasyOCR reader.
        connection: SQLite connection backing the offline hit queue.
        voter: Temporal voting window tracker.
        plate_index: Monotonic tracker id assigned to each plate crop.
        last_flush_time: Epoch seconds of the last queue flush.
    """

    args: argparse.Namespace
    device_token: str
    yolo_model: Any
    reader: Any
    connection: sqlite3.Connection
    voter: TemporalVoter
    plate_index: int = 0
    last_flush_time: float = field(default_factory=time.time)


def _load_detection_models() -> tuple[Any, Any]:
    """Import and construct the YOLO and EasyOCR models.

    Returns:
        tuple[Any, Any]: The YOLO model and the EasyOCR reader.
    """
    import easyocr
    import ultralytics

    logger.info("loading_models")
    yolo_model = ultralytics.YOLO(YOLO_WEIGHTS)
    ocr_reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
    logger.info("models_loaded")
    return yolo_model, ocr_reader


def _resolve_device_token(args: argparse.Namespace) -> str:
    """Return the device token, registering a device when none was given.

    Args:
        args: Parsed command-line arguments.

    Returns:
        str: The device authentication token.

    Raises:
        SystemExit: When no token or credentials were supplied.
    """
    if args.device_token:
        return args.device_token
    if not args.device_email or not args.device_password:
        logger.error(
            "missing_credentials",
            msg="Provide --device-token or --device-email + --device-password",
        )
        sys.exit(1)

    device_id, device_token = register_device(
        backend_url=args.backend,
        email=args.device_email,
        password=args.device_password,
    )
    logger.info("device_token_obtained", device_id=device_id)
    return device_token


def _queue_matched_hit(
    frame: np.ndarray,
    context: SimulationContext,
    agreed_plate: str,
    confidence: int,
    stats: SimulationStats,
) -> None:
    """Queue a matched hit in the offline SQLite queue.

    Args:
        frame: The full frame the plate was found in (used as the photo).
        context: Shared run state.
        agreed_plate: The temporally agreed plate string.
        confidence: OCR confidence for this hit.
        stats: Mutable counters for this run.
    """
    stats.match_count += 1
    queue_hit(
        conn=context.connection,
        plate=agreed_plate,
        lat=context.args.lat,
        lng=context.args.lng,
        captured_at=datetime.now(timezone.utc).isoformat(),
        confidence=confidence,
        photo_b64=encode_frame_jpeg(frame),
    )
    logger.info(
        "hit_queued",
        plate=agreed_plate,
        frame=stats.frame_number,
        confidence=confidence,
    )


def _evaluate_crop(
    plate_crop: np.ndarray,
    frame: np.ndarray,
    context: SimulationContext,
    stats: SimulationStats,
) -> None:
    """OCR a plate crop, apply temporal voting, and queue a matching hit.

    Args:
        plate_crop: Cropped plate image detected by YOLO.
        frame: The full frame the crop came from.
        context: Shared run state.
        stats: Mutable counters for this run.
    """
    context.plate_index += 1
    raw_text, confidence = ocr_plate(plate_crop, context.reader)
    if not raw_text:
        return

    normalised = normalise_plate(raw_text)
    if not normalised:
        return

    stats.detection_count += 1
    agreed_plate = context.voter.vote(context.plate_index, normalised)
    if agreed_plate is None or agreed_plate != context.args.plate.upper():
        return

    _queue_matched_hit(frame, context, agreed_plate, confidence, stats)


def _process_frame(
    frame: np.ndarray,
    context: SimulationContext,
    stats: SimulationStats,
) -> None:
    """Quality-filter a frame and evaluate every plate detected in it.

    Args:
        frame: The decoded BGR frame.
        context: Shared run state.
        stats: Mutable counters for this run.
    """
    stats.frame_number += 1
    if not is_frame_usable(frame):
        logger.debug("frame_rejected", frame=stats.frame_number, reason="blur_or_dark")
        return

    for plate_crop in detect_plates(frame, context.yolo_model):
        _evaluate_crop(plate_crop, frame, context, stats)


def _flush_queue_if_due(context: SimulationContext, stats: SimulationStats) -> None:
    """Flush the offline queue when the flush interval has elapsed.

    Args:
        context: Shared run state.
        stats: Mutable counters for this run.
    """
    now = time.time()
    if now - context.last_flush_time < FLUSH_INTERVAL_SECONDS:
        return

    flushed = flush_queue(context.connection, context.args.backend, context.device_token)
    if flushed > 0:
        stats.sent_count += flushed
        logger.info("queue_flushed", flushed=flushed, total_sent=stats.sent_count)
    context.last_flush_time = now


def _run_video_pass(context: SimulationContext, stats: SimulationStats) -> None:
    """Play the configured video once, processing every frame.

    Args:
        context: Shared run state.
        stats: Mutable counters for this run.

    Raises:
        SystemExit: When the video file cannot be opened.
    """
    capture = cv2.VideoCapture(context.args.video)
    if not capture.isOpened():
        logger.error("video_open_failed", path=context.args.video)
        sys.exit(1)

    try:
        while True:
            ret, frame = capture.read()
            if not ret:
                break

            _process_frame(frame, context, stats)
            _flush_queue_if_due(context, stats)

            logger.info(
                "frame_processed",
                frame=stats.frame_number,
                detections=stats.detection_count,
                matches=stats.match_count,
                sent=stats.sent_count,
            )
            cv2.waitKey(FRAME_INTERVAL_MS)
    finally:
        capture.release()


def run_simulation(args: argparse.Namespace) -> None:
    """Run the main device simulation loop.

    Loads models, processes video frames, detects plates, runs OCR,
    normalises plates, applies temporal voting, and sends matching hits
    to the backend.

    Args:
        args: Parsed command-line arguments.
    """
    device_token = _resolve_device_token(args)
    yolo_model, ocr_reader = _load_detection_models()

    context = SimulationContext(
        args=args,
        device_token=device_token,
        yolo_model=yolo_model,
        reader=ocr_reader,
        connection=init_offline_db(OFFLINE_DB_PATH),
        voter=TemporalVoter(),
    )
    stats = SimulationStats()

    logger.info(
        "simulation_start",
        video=args.video,
        target_plate=args.plate,
        backend=args.backend,
        lat=args.lat,
        lng=args.lng,
        loop=args.loop,
    )

    while True:
        _run_video_pass(context, stats)
        if not args.loop:
            break
        logger.info("loop_restart", video=args.video)

    stats.sent_count += flush_queue(context.connection, args.backend, device_token)
    context.connection.close()

    logger.info(
        "simulation_complete",
        frames=stats.frame_number,
        detections=stats.detection_count,
        matches=stats.match_count,
        sent=stats.sent_count,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the video, target plate, and loop arguments.

    Args:
        parser: Argument parser under construction.

    Returns:
        None.
    """
    parser.add_argument(
        "--video",
        required=True,
        help="Path to input video file",
    )
    parser.add_argument(
        "--plate",
        required=True,
        help="Licence plate to treat as hotlisted (e.g. MH12AB1234)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop the video continuously",
    )


def _add_device_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the backend URL and device authentication arguments.

    Args:
        parser: Argument parser under construction.

    Returns:
        None.
    """
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND_URL,
        help=(
            f"Backend URL (default: ${BACKEND_URL_ENV_VAR} or "
            f"{DEFAULT_BACKEND_URL})"
        ),
    )
    parser.add_argument(
        "--device-token",
        default=None,
        help="Device authentication token (if already registered)",
    )
    parser.add_argument(
        "--device-email",
        default=None,
        help="User email for device registration (used if --device-token not provided)",
    )
    parser.add_argument(
        "--device-password",
        default=None,
        help="User password for device registration",
    )


def _add_location_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the latitude and longitude arguments for hit events.

    Args:
        parser: Argument parser under construction.

    Returns:
        None.
    """
    parser.add_argument(
        "--lat",
        type=float,
        default=DEFAULT_LAT,
        help=f"Latitude for hit events (default: {DEFAULT_LAT})",
    )
    parser.add_argument(
        "--lng",
        type=float,
        default=DEFAULT_LNG,
        help=f"Longitude for hit events (default: {DEFAULT_LNG})",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the device simulator.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="RAKSHAK device simulator — offline ANPR detection pipeline",
    )
    _add_source_arguments(parser)
    _add_device_arguments(parser)
    _add_location_arguments(parser)
    return parser.parse_args()


def main() -> None:
    """Entry point: parse arguments and start the simulation.

    Returns:
        None.
    """
    run_simulation(parse_args())


if __name__ == "__main__":
    main()
