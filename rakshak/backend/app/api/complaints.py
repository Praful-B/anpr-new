"""Complaint endpoints — filing, listing, FIR submission, and verification.

Routes under ``/api/v1/complaints`` handle the full complaint lifecycle:
creation by citizens/volunteers (with optional proof file upload via multipart),
listing personal complaints, FIR reference submission, and COP/ADMIN verification.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import redis
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, get_redis, require_role
from app.models.complaint import Complaint, ComplaintStatus
from app.models.hotlist import Hotlist, HotlistStatus
from app.models.user import Role, User
from app.schemas.complaint import (
    ComplaintResponse,
    FIRSubmit,
    VerifyRequest,
)
from app.services import notifier
from app.services.audit import (
    ACTION_COMPLAINT_VERIFY,
    TARGET_COMPLAINT,
    write_audit_log,
)
from app.services.storage import get_storage
from app.services.verification import verify_complaint

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/complaints", tags=["complaints"])

logger = structlog.get_logger(__name__)

RATE_LIMIT_USER_MAX = 3
RATE_LIMIT_IP_MAX = 10
RATE_LIMIT_WINDOW_SECONDS = 86400
RATE_LIMIT_USER_KEY_PREFIX = "rate:complaints:user"
RATE_LIMIT_IP_KEY_PREFIX = "rate:complaints:ip"
UNKNOWN_CLIENT_IP = "unknown"
DEFAULT_CONTENT_TYPE = "application/octet-stream"

MAX_PROOF_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_PROOF_FILE_SIZE_MB = MAX_PROOF_FILE_SIZE_BYTES // (1024 * 1024)

_PLATE_NORMALISE_RE = re.compile(r"[\s\-]")


def _normalise_plate(plate: str) -> str:
    """Normalise a licence plate to uppercase with no spaces or hyphens.

    Args:
        plate: Raw plate string from the user.

    Returns:
        str: Normalised plate (uppercase, no whitespace/hyphens).
    """
    return _PLATE_NORMALISE_RE.sub("", plate).upper()


def _check_rate_limit(
    r: redis.Redis,
    key_prefix: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    """Check and enforce a Redis-based sliding window rate limit.

    Args:
        r: Redis client instance.
        key_prefix: Prefix for the Redis key (e.g., ``rate:complaints:user``).
        identifier: Unique identifier (user ID or IP address).
        max_requests: Maximum allowed requests within the window.
        window_seconds: Time window in seconds.

    Raises:
        HTTPException: 429 if the rate limit is exceeded.
    """
    now = datetime.now(timezone.utc)
    day_str = now.strftime("%Y-%m-%d")
    key = f"{key_prefix}:{identifier}:{day_str}"

    current = r.get(key)
    if current is not None and int(current) >= max_requests:
        ttl = r.ttl(key)
        retry_after = max(ttl, 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    pipe.execute()


def _load_complaint(db: Session, complaint_id: uuid.UUID) -> Complaint:
    """Load a complaint by id or fail with 404.

    Args:
        db: Database session.
        complaint_id: UUID of the complaint.

    Returns:
        Complaint: The matching ORM instance.

    Raises:
        HTTPException: 404 when the complaint does not exist.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found",
        )
    return complaint


def _enforce_complaint_rate_limits(
    r: redis.Redis,
    request: Request,
    current_user: User,
) -> None:
    """Apply the per-user and per-IP complaint rate limits.

    Args:
        r: Redis client instance.
        request: FastAPI request used to derive the client IP.
        current_user: The user filing the complaint.

    Raises:
        HTTPException: 429 when either limit is exceeded.
    """
    client_ip = request.client.host if request.client else UNKNOWN_CLIENT_IP
    _check_rate_limit(
        r,
        RATE_LIMIT_USER_KEY_PREFIX,
        str(current_user.id),
        RATE_LIMIT_USER_MAX,
        RATE_LIMIT_WINDOW_SECONDS,
    )
    _check_rate_limit(
        r,
        RATE_LIMIT_IP_KEY_PREFIX,
        client_ip,
        RATE_LIMIT_IP_MAX,
        RATE_LIMIT_WINDOW_SECONDS,
    )


async def _store_proof_file(proof: UploadFile | None) -> str | None:
    """Persist an uploaded proof file through the storage backend.

    Args:
        proof: The optional uploaded proof file.

    Returns:
        str | None: Storage URL for the proof, or None when nothing was
        uploaded.

    Raises:
        HTTPException: 413 when the file exceeds the size ceiling.
    """
    if proof is None or not proof.filename:
        return None

    contents = await proof.read()
    if len(contents) > MAX_PROOF_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Proof file exceeds maximum size of {MAX_PROOF_FILE_SIZE_MB} MB",
        )

    proof_ref = get_storage().put(contents, content_type=proof.content_type or DEFAULT_CONTENT_TYPE)
    logger.info("complaint_proof_uploaded", path=proof_ref, size=len(contents))
    return proof_ref


def _load_complaint_for_owner(
    db: Session,
    complaint_id: uuid.UUID,
    current_user: User,
) -> Complaint:
    """Load a complaint and assert that the caller owns it.

    Args:
        db: Database session.
        complaint_id: UUID of the complaint.
        current_user: The authenticated user filing the FIR.

    Returns:
        Complaint: The owned complaint.

    Raises:
        HTTPException: 404 when missing, 403 when owned by another user.
    """
    complaint = _load_complaint(db, complaint_id)
    if complaint.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit FIR for your own complaints",
        )
    return complaint


def _find_awaiting_fir_hotlist(db: Session, complaint_id: uuid.UUID) -> Hotlist:
    """Find the ACTIVE_UNCONFIRMED hotlist entry awaiting an FIR reference.

    Args:
        db: Database session.
        complaint_id: UUID of the verified complaint.

    Returns:
        Hotlist: The hotlist entry that will receive the FIR reference.

    Raises:
        HTTPException: 409 when no such entry exists.
    """
    hotlist_entry = (
        db.query(Hotlist)
        .filter(
            Hotlist.complaint_id == complaint_id,
            Hotlist.status == HotlistStatus.ACTIVE_UNCONFIRMED,
        )
        .first()
    )
    if hotlist_entry is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active hotlist entry found for this complaint",
        )
    return hotlist_entry


def _notify_hotlist_change(db: Session, complaint_id: uuid.UUID) -> None:
    """Push a hotlist-change event when verification created a hotlist entry.

    Args:
        db: Database session.
        complaint_id: UUID of the just-verified complaint.

    Returns:
        None.
    """
    hotlist_entry = (
        db.query(Hotlist).filter(Hotlist.complaint_id == complaint_id).first()
    )
    if hotlist_entry is None:
        return
    notifier.schedule(
        notifier.push_hotlist_change(notifier.hotlist_payload(hotlist_entry))
    )


def _record_verification_audit(
    db: Session,
    actor: User,
    complaint: Complaint,
    payload: VerifyRequest,
) -> None:
    """Write an audit entry for a complaint verification decision.

    Args:
        db: Database session.
        actor: The COP or ADMIN who made the decision.
        complaint: The complaint that was verified or rejected.
        payload: The verification request that was applied.
    """
    hotlist_entry = (
        db.query(Hotlist).filter(Hotlist.complaint_id == complaint.id).first()
    )
    write_audit_log(
        db=db,
        actor_id=actor.id,
        action=ACTION_COMPLAINT_VERIFY,
        target_type=TARGET_COMPLAINT,
        target_id=complaint.id,
        metadata={
            "decision": payload.decision,
            "reason": payload.reason,
            "hotlist_id": str(hotlist_entry.id) if hotlist_entry else None,
        },
    )


def _complaint_to_response(complaint: Complaint) -> ComplaintResponse:
    """Convert a Complaint ORM instance to the response schema.

    Args:
        complaint: The complaint ORM instance.

    Returns:
        ComplaintResponse: Pydantic model safe for external responses.
    """
    return ComplaintResponse(
        id=complaint.id,
        user_id=complaint.user_id,
        plate=complaint.plate,
        proof_ref=complaint.proof_ref,
        status=complaint.status.value,
        rejection_reason=complaint.rejection_reason,
        created_at=complaint.created_at,
        updated_at=complaint.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_complaint(
    request: Request,
    current_user: Annotated[User, Depends(require_role(Role.CITIZEN, Role.VOLUNTEER))],
    db: Annotated[Session, Depends(get_db)],
    r: Annotated[redis.Redis, Depends(get_redis)],
    plate: Annotated[str, Form()],
    notes: Annotated[str | None, Form()] = None,
    proof: Annotated[UploadFile | None, File()] = None,
) -> ComplaintResponse:
    """File a new stolen-vehicle complaint.

    Accepts multipart form data with a licence plate (required), optional
    notes, and an optional proof file (image, video, or PDF). The proof file
    is stored via the configured StorageBackend and its URL is saved as the
    complaint's ``proof_ref``.

    Rate limited to 3 per user per 24 hours and 10 per IP per 24 hours.

    Args:
        request: FastAPI request for IP extraction.
        plate: Licence plate string (will be normalised server-side).
        notes: Optional free-text notes about the incident.
        proof: Optional uploaded proof file.
        current_user: Authenticated CITIZEN or VOLUNTEER user.
        db: Database session.
        r: Redis client for rate limiting.

    Returns:
        ComplaintResponse: The created complaint.

    Raises:
        HTTPException: 429 if rate limit is exceeded, 400 if file is too large.
    """
    _enforce_complaint_rate_limits(r, request, current_user)

    normalised_plate = _normalise_plate(plate)
    proof_ref = await _store_proof_file(proof)

    complaint = Complaint(
        user_id=current_user.id,
        plate=normalised_plate,
        proof_ref=proof_ref,
        status=ComplaintStatus.PENDING_VERIFICATION,
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    logger.info(
        "complaint_created",
        complaint_id=str(complaint.id),
        user_id=str(current_user.id),
        plate=normalised_plate,
    )

    return _complaint_to_response(complaint)


@router.get(
    "/mine",
    response_model=list[ComplaintResponse],
)
def get_my_complaints(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ComplaintResponse]:
    """List all complaints filed by the current user.

    Args:
        current_user: Authenticated user.
        db: Database session.

    Returns:
        list[ComplaintResponse]: The user's complaints, newest first.
    """
    complaints = (
        db.query(Complaint)
        .filter(Complaint.user_id == current_user.id)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return [_complaint_to_response(c) for c in complaints]


@router.post(
    "/{complaint_id}/fir",
    status_code=status.HTTP_200_OK,
)
def submit_fir(
    complaint_id: uuid.UUID,
    payload: FIRSubmit,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Submit an FIR reference for a verified complaint.

    The complaint must be in VERIFIED state with an existing hotlist
    entry in ACTIVE_UNCONFIRMED status.

    Args:
        complaint_id: UUID of the complaint.
        payload: FIR reference data.
        current_user: Authenticated user (must own the complaint).
        db: Database session.

    Returns:
        dict: Confirmation with the FIR reference.

    Raises:
        HTTPException: 404 if complaint not found, 403 if not owner,
            409 if complaint is not verified or hotlist entry not found.
    """
    complaint = _load_complaint_for_owner(db, complaint_id, current_user)
    if complaint.status != ComplaintStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Complaint must be verified before submitting FIR (current status: {complaint.status.value})",
        )

    hotlist_entry = _find_awaiting_fir_hotlist(db, complaint_id)
    hotlist_entry.fir_ref = payload.fir_ref.strip()
    hotlist_entry.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "fir_submitted",
        complaint_id=str(complaint_id),
        hotlist_entry_id=str(hotlist_entry.id),
        fir_ref=hotlist_entry.fir_ref,
    )

    return {"fir_ref": hotlist_entry.fir_ref, "hotlist_entry_id": str(hotlist_entry.id)}


@router.post(
    "/{complaint_id}/verify",
    response_model=ComplaintResponse,
)
def verify_complaint_endpoint(
    complaint_id: uuid.UUID,
    payload: VerifyRequest,
    current_user: Annotated[User, Depends(require_role(Role.COP, Role.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> ComplaintResponse:
    """Verify (approve or reject) a complaint. COP/ADMIN only.

    On approve: creates a hotlist entry with ACTIVE_UNCONFIRMED status
    and a 48-hour FIR deadline.

    On reject: marks the complaint as REJECTED with the provided reason.

    Args:
        complaint_id: UUID of the complaint to verify.
        payload: Verification decision and optional reason.
        current_user: Authenticated COP or ADMIN user.
        db: Database session.

    Returns:
        ComplaintResponse: The updated complaint.

    Raises:
        HTTPException: 404 if complaint not found, 400 on validation error.
    """
    complaint = _load_complaint(db, complaint_id)

    try:
        complaint = verify_complaint(
            db=db,
            complaint=complaint,
            decision=payload.decision,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    _notify_hotlist_change(db, complaint_id)
    _record_verification_audit(db, current_user, complaint, payload)

    logger.info(
        "complaint_verified",
        complaint_id=str(complaint_id),
        decision=payload.decision,
        actor_id=str(current_user.id),
    )

    return _complaint_to_response(complaint)
