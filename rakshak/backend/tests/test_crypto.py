"""Cryptographic primitive tests — HKDF key derivation and AES-GCM encryption.

Covers round-trip encrypt/decrypt, wrong-key rejection (InvalidTag),
HKDF determinism for identical inputs, and key wrapping.
"""

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.services.crypto import (
    HKDF_KEY_LENGTH,
    decrypt_hotlist,
    derive_device_key,
    encrypt_hotlist,
    wrap_key_for_device,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_MASTER_KEY = os.urandom(32)
TEST_DEVICE_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_VERSION = 1700000000


# ---------------------------------------------------------------------------
# HKDF key derivation tests
# ---------------------------------------------------------------------------


def test_derive_device_key_returns_32_bytes() -> None:
    """HKDF derivation must produce exactly 32 bytes.

    Raises:
        AssertionError: If the derived key length is not 32.
    """
    key = derive_device_key(TEST_MASTER_KEY, TEST_DEVICE_ID, TEST_VERSION)
    assert len(key) == HKDF_KEY_LENGTH


def test_derive_device_key_deterministic_for_same_inputs() -> None:
    """Identical inputs must always produce the same derived key.

    Raises:
        AssertionError: If two derivations with the same inputs differ.
    """
    key1 = derive_device_key(TEST_MASTER_KEY, TEST_DEVICE_ID, TEST_VERSION)
    key2 = derive_device_key(TEST_MASTER_KEY, TEST_DEVICE_ID, TEST_VERSION)
    assert key1 == key2


def test_derive_device_key_different_for_different_versions() -> None:
    """Different version numbers must produce different keys.

    Raises:
        AssertionError: If keys for different versions are identical.
    """
    key_v1 = derive_device_key(TEST_MASTER_KEY, TEST_DEVICE_ID, 1)
    key_v2 = derive_device_key(TEST_MASTER_KEY, TEST_DEVICE_ID, 2)
    assert key_v1 != key_v2


def test_derive_device_key_different_for_different_devices() -> None:
    """Different device IDs must produce different keys.

    Raises:
        AssertionError: If keys for different devices are identical.
    """
    key_a = derive_device_key(TEST_MASTER_KEY, "device-a", TEST_VERSION)
    key_b = derive_device_key(TEST_MASTER_KEY, "device-b", TEST_VERSION)
    assert key_a != key_b


# ---------------------------------------------------------------------------
# AES-GCM encrypt / decrypt round-trip tests
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    """Encrypting and decrypting with the same key recovers original plates.

    Raises:
        AssertionError: If decrypted plates do not match originals.
    """
    plates = ["MH12AB1234", "DL01CD5678", "KA01EF9012"]
    key = os.urandom(32)

    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, key)
    decrypted = decrypt_hotlist(iv_b64, ciphertext_b64, key)

    assert decrypted == plates


def test_encrypt_decrypt_empty_list() -> None:
    """Encrypting an empty plate list must round-trip correctly.

    Raises:
        AssertionError: If the decrypted result is not an empty list.
    """
    plates: list[str] = []
    key = os.urandom(32)

    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, key)
    decrypted = decrypt_hotlist(iv_b64, ciphertext_b64, key)

    assert decrypted == []


def test_encrypt_produces_base64_strings() -> None:
    """The IV and ciphertext must be valid base64-encoded strings.

    Raises:
        AssertionError: If decoding from base64 fails.
    """
    plates = ["MH12AB1234"]
    key = os.urandom(32)

    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, key)

    iv_bytes = base64.b64decode(iv_b64)
    ct_bytes = base64.b64decode(ciphertext_b64)
    assert len(iv_bytes) == 12
    assert len(ct_bytes) > 0


def test_decrypt_wrong_key_raises_invalid_tag() -> None:
    """Decryption with a wrong key must raise InvalidTag.

    Raises:
        AssertionError: If InvalidTag is not raised.
    """
    plates = ["MH12AB1234"]
    correct_key = os.urandom(32)
    wrong_key = os.urandom(32)

    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, correct_key)

    with pytest.raises(InvalidTag):
        decrypt_hotlist(iv_b64, ciphertext_b64, wrong_key)


def test_decrypt_tampered_ciphertext_bit_flip_raises_invalid_tag() -> None:
    """Flipping any ciphertext bit must make decryption fail with InvalidTag.

    AES-GCM authenticates ciphertext, so a single modified byte must be
    detected even when the key is correct.

    Raises:
        AssertionError: If tampered ciphertext decrypts without error.
    """
    plates = ["MH12AB1234", "DL01CD5678"]
    key = os.urandom(32)

    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, key)
    ciphertext = bytearray(base64.b64decode(ciphertext_b64))
    ciphertext[0] ^= 0x01
    tampered_ct = base64.b64encode(bytes(ciphertext)).decode("ascii")

    with pytest.raises(InvalidTag):
        decrypt_hotlist(iv_b64, tampered_ct, key)


def test_decrypt_tampered_iv_bit_flip_raises_invalid_tag() -> None:
    """Flipping any IV bit must make decryption fail with InvalidTag.

    The GCM authentication tag is bound to the IV as well as the
    ciphertext, so a modified IV must be detected.

    Raises:
        AssertionError: If tampered IV decrypts without error.
    """
    plates = ["MH12AB1234", "DL01CD5678"]
    key = os.urandom(32)

    iv_b64, ciphertext_b64 = encrypt_hotlist(plates, key)
    iv = bytearray(base64.b64decode(iv_b64))
    iv[0] ^= 0x01
    tampered_iv = base64.b64encode(bytes(iv)).decode("ascii")

    with pytest.raises(InvalidTag):
        decrypt_hotlist(tampered_iv, ciphertext_b64, key)


def test_encrypt_wrong_key_length_raises() -> None:
    """Encryption with a non-32-byte key must raise ValueError.

    Raises:
        AssertionError: If ValueError is not raised.
    """
    plates = ["MH12AB1234"]
    short_key = os.urandom(16)

    with pytest.raises(ValueError, match="32 bytes"):
        encrypt_hotlist(plates, short_key)


def test_decrypt_wrong_key_length_raises() -> None:
    """Decryption with a non-32-byte key must raise ValueError.

    Raises:
        AssertionError: If ValueError is not raised.
    """
    iv_b64 = base64.b64encode(os.urandom(12)).decode()
    ciphertext_b64 = base64.b64encode(os.urandom(32)).decode()
    short_key = os.urandom(16)

    with pytest.raises(ValueError, match="32 bytes"):
        decrypt_hotlist(iv_b64, ciphertext_b64, short_key)


# ---------------------------------------------------------------------------
# Key wrapping tests
# ---------------------------------------------------------------------------


def test_wrap_key_for_device_returns_json() -> None:
    """wrap_key_for_device must return a JSON string with iv and ciphertext.

    Raises:
        AssertionError: If the output is not valid JSON with expected keys.
    """
    import json

    device_key = os.urandom(32)
    master_key = os.urandom(32)

    wrapped = wrap_key_for_device(device_key, master_key)
    parsed = json.loads(wrapped)

    assert "iv" in parsed
    assert "ciphertext" in parsed
    assert isinstance(parsed["iv"], str)
    assert isinstance(parsed["ciphertext"], str)


def test_wrap_key_wrong_master_key_length_raises() -> None:
    """Wrapping with a non-32-byte master key must raise ValueError.

    Raises:
        AssertionError: If ValueError is not raised.
    """
    device_key = os.urandom(32)
    bad_master = os.urandom(16)

    with pytest.raises(ValueError, match="32 bytes"):
        wrap_key_for_device(device_key, bad_master)
