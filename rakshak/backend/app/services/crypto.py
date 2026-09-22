"""Cryptographic primitives — HKDF key derivation, AES-256-GCM encrypt/decrypt.

Provides per-device encryption key derivation using HKDF-SHA256 and
AES-256-GCM authenticated encryption for the hotlist sync payload.
"""

import base64
import json
import os

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

HKDF_INFO_PREFIX = b"rakshak-device-key"
HKDF_KEY_LENGTH = 32
AES_GCM_IV_LENGTH = 12


def derive_device_key(
    master_key: bytes,
    device_id: str,
    version: int,
) -> bytes:
    """Derive a per-device AES-256 encryption key using HKDF-SHA256.

    The derivation uses ``master_key`` as the input key material,
    ``device_id`` encoded as UTF-8 as the info parameter, and
    ``version`` encoded as a big-endian 8-byte integer as the salt.

    Args:
        master_key: 32-byte master key from ``MASTER_KEY_B64``.
        device_id: UUID string of the device.
        version: Integer epoch version of the hotlist snapshot.

    Returns:
        bytes: A 32-byte derived key suitable for AES-256-GCM.
    """
    info = HKDF_INFO_PREFIX + device_id.encode("utf-8")
    salt = version.to_bytes(8, byteorder="big")

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=HKDF_KEY_LENGTH,
        salt=salt,
        info=info,
    )
    derived = hkdf.derive(master_key)
    logger.debug(
        "device_key_derived",
        device_id=device_id,
        version=version,
    )
    return derived


def encrypt_hotlist(
    plates: list[str],
    key: bytes,
) -> tuple[str, str]:
    """Encrypt a list of plate strings using AES-256-GCM.

    The plaintext payload is a JSON-serialised list of plate strings.
    A fresh random 12-byte IV is generated for each call.

    Args:
        plates: List of normalised licence plate strings.
        key: 32-byte AES-256 encryption key.

    Returns:
        tuple[str, str]: A pair of (iv_b64, ciphertext_b64) where both
            are base64-encoded strings.

    Raises:
        ValueError: If the key is not 32 bytes.
    """
    if len(key) != HKDF_KEY_LENGTH:
        raise ValueError(
            f"Encryption key must be {HKDF_KEY_LENGTH} bytes, got {len(key)}"
        )

    iv = os.urandom(AES_GCM_IV_LENGTH)
    plaintext = json.dumps(plates).encode("utf-8")

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)

    iv_b64 = base64.b64encode(iv).decode("ascii")
    ciphertext_b64 = base64.b64encode(ciphertext).decode("ascii")

    logger.debug(
        "hotlist_encrypted",
        plate_count=len(plates),
    )
    return iv_b64, ciphertext_b64


def decrypt_hotlist(
    iv_b64: str,
    ciphertext_b64: str,
    key: bytes,
) -> list[str]:
    """Decrypt an AES-256-GCM ciphertext back to a list of plate strings.

    Args:
        iv_b64: Base64-encoded 12-byte IV used during encryption.
        ciphertext_b64: Base64-encoded AES-256-GCM ciphertext.
        key: 32-byte AES-256 decryption key.

    Returns:
        list[str]: The decrypted list of normalised plate strings.

    Raises:
        ValueError: If the key is not 32 bytes.
        cryptography.exceptions.InvalidTag: If decryption fails
            (wrong key or corrupted ciphertext).
    """
    if len(key) != HKDF_KEY_LENGTH:
        raise ValueError(
            f"Decryption key must be {HKDF_KEY_LENGTH} bytes, got {len(key)}"
        )

    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ciphertext_b64)

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    plates: list[str] = json.loads(plaintext.decode("utf-8"))

    logger.debug(
        "hotlist_decrypted",
        plate_count=len(plates),
    )
    return plates


def wrap_key_for_device(device_key: bytes, master_key: bytes) -> str:
    """Wrap a device encryption key using the master key via AES-GCM.

    Encrypts ``device_key`` with ``master_key`` using a random IV.
    The result is stored as a JSON string containing ``iv`` and
    ``ciphertext`` fields, both base64-encoded.

    Args:
        device_key: 32-byte per-device encryption key.
        master_key: 32-byte master key used as the wrapping key.

    Returns:
        str: JSON string ``{"iv": "<b64>", "ciphertext": "<b64>"}``.
    """
    if len(device_key) != HKDF_KEY_LENGTH:
        raise ValueError(
            f"Device key must be {HKDF_KEY_LENGTH} bytes, got {len(device_key)}"
        )
    if len(master_key) != HKDF_KEY_LENGTH:
        raise ValueError(
            f"Master key must be {HKDF_KEY_LENGTH} bytes, got {len(master_key)}"
        )

    iv = os.urandom(AES_GCM_IV_LENGTH)
    aesgcm = AESGCM(master_key)
    ciphertext = aesgcm.encrypt(iv, device_key, None)

    wrapped = {
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(wrapped)
