"""Detection endpoint — prototype fallback for on-device inference.

POST /api/v1/detect accepts a base64-encoded camera frame and runs the
same YOLO+OCR pipeline server-side, returning detected plates.

THIS ENDPOINT EXISTS ONLY AS A PROTOTYPE FALLBACK and violates the
zero-retention promise if used in production. The mobile app's TFLite
integration is the intended production path. See ARCHITECTURE.md.
"""

import base64
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.deps import get_current_device
from app.models.device import Device
from app.services.normalizer import normalise_plate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(tags=["detect"])

logger = structlog.get_logger(__name__)

MAX_FRAME_B64_LENGTH = 10 * 1024 * 1024
MIN_CONFIDENCE = 40
DETECTION_MODEL_WEIGHTS = "yolo11n.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.25
OCR_LANGUAGES = ["en"]

# Optional computer-vision dependencies. They are imported defensively so the
# API still boots when the heavy CV extras are not installed.
try:
    import cv2
    import easyocr
    import numpy as np
    from ultralytics import YOLO

    DETECTION_AVAILABLE = True
except ImportError:
    DETECTION_AVAILABLE = False


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DetectRequest(BaseModel):
    """Schema for the detect request payload.

    Attributes:
        frame_b64: Base64-encoded JPEG camera frame.
    """

    frame_b64: str = Field(
        ...,
        max_length=MAX_FRAME_B64_LENGTH,
        description="Base64-encoded camera frame",
    )


class DetectedPlate(BaseModel):
    """Schema for a single detected plate.

    Attributes:
        plate: Normalised licence plate string.
        confidence: Detection confidence (0-100).
    """

    plate: str = Field(..., description="Normalised licence plate")
    confidence: int = Field(..., ge=0, le=100, description="Confidence score")


class DetectResponse(BaseModel):
    """Schema for the detect response payload.

    Attributes:
        plates: List of detected plates above confidence threshold.
    """

    plates: list[DetectedPlate] = Field(
        ...,
        description="Detected plates",
    )


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------


def _decode_frame(frame_b64: str) -> "np.ndarray | None":
    """Decode a base64 JPEG frame into an OpenCV BGR image array.

    Args:
        frame_b64: Base64-encoded JPEG frame.

    Returns:
        np.ndarray | None: The decoded image, or None when decoding fails.
    """
    frame_bytes = base64.b64decode(frame_b64)
    buffer = np.frombuffer(frame_bytes, np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _ocr_crop(crop: "np.ndarray") -> list[DetectedPlate]:
    """Run OCR on a cropped plate region and normalise the results.

    Args:
        crop: Cropped plate image extracted from the frame.

    Returns:
        list[DetectedPlate]: Detections at or above the confidence floor.
    """
    reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
    detections: list[DetectedPlate] = []

    for _, text, confidence in reader.readtext(crop):
        raw_plate = text.strip()
        if not raw_plate:
            continue
        score = int(confidence * 100)
        if score < MIN_CONFIDENCE:
            continue
        detections.append(
            DetectedPlate(plate=normalise_plate(raw_plate), confidence=score)
        )

    return detections


def _detect_in_frame(frame: "np.ndarray") -> list[DetectedPlate]:
    """Detect plate regions with YOLO and OCR each crop.

    Args:
        frame: Decoded BGR camera frame.

    Returns:
        list[DetectedPlate]: All plates found in the frame.
    """
    detections: list[DetectedPlate] = []
    model = YOLO(DETECTION_MODEL_WEIGHTS)
    results = model(frame, conf=YOLO_CONFIDENCE_THRESHOLD, verbose=False)

    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            detections.extend(_ocr_crop(crop))

    return detections


def _run_detection_pipeline(frame_b64: str) -> list[DetectedPlate]:
    """Run the YOLO+OCR detection pipeline on a base64 frame.

    Uses ultralytics YOLO for plate detection and easyocr for OCR,
    matching the pipeline used by the device simulator in scripts/.

    Args:
        frame_b64: Base64-encoded JPEG frame.

    Returns:
        list[DetectedPlate]: Detected plates above confidence threshold.
    """
    if not DETECTION_AVAILABLE:
        logger.warning("detection_dependencies_missing")
        return []

    try:
        frame = _decode_frame(frame_b64)
        if frame is None:
            return []
        return _detect_in_frame(frame)
    except Exception as exc:
        logger.error("detection_pipeline_error", error=str(exc))
        return []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/detect",
    response_model=DetectResponse,
    status_code=status.HTTP_200_OK,
)
def detect_plates_endpoint(
    payload: DetectRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
) -> DetectResponse:
    """Detect licence plates in a camera frame (prototype fallback).

    THIS ENDPOINT IS A PROTOTYPE FALLBACK ONLY. In production, plate
    detection should happen on-device via TFLite. Using this endpoint
    sends raw camera frames to the server, which violates the
    zero-retention privacy promise.

    Args:
        payload: Base64-encoded camera frame.
        current_device: Authenticated device from X-Device-Token.

    Returns:
        DetectResponse: List of detected plates with confidence scores. An
            undecodable frame yields an empty list rather than an error.
    """
    logger.warning(
        "detect_endpoint_used",
        device_id=str(current_device.id),
        note="Prototype fallback — violates zero-retention if used in production",
    )

    return DetectResponse(plates=_run_detection_pipeline(payload.frame_b64))
