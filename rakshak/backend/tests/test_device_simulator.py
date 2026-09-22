"""Unit tests for the host-side device simulator pipeline (scripts/device_simulator.py).

Covers the Flow C steps that are pure Python on this host: plate
normalisation (§8), frame quality filtering, temporal voting, JPEG encoding,
and the SQLite offline queue roundtrip. The YOLO/EasyOCR model loaders
(_load_detection_models) are lazily imported and excluded here.

Requires numpy + opencv-python-headless + requests in the test environment
(the heavy ultralytics/easyocr stack stays out).
"""

import base64
import sys
import tempfile
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.device_simulator as sim


# ---------------------------------------------------------------------------
# Plate normalisation
# ---------------------------------------------------------------------------


class TestNormalisePlate:
    """Plate normalisation parity with the §8 Indian format."""

    def test_valid_plate_passes_through_unchanged(self):
        """A canonical plate is returned untouched."""
        assert sim.normalise_plate("MH12AB1234") == "MH12AB1234"

    def test_strips_spaces_and_hyphens_and_uppercases(self):
        """Whitespace, hyphens and case are normalised first."""
        assert sim.normalise_plate("mh-12 ab 1234") == "MH12AB1234"

    def test_returns_empty_for_blank_input(self):
        """Blank OCR input cannot produce a plate."""
        assert sim.normalise_plate("") == ""
        assert sim.normalise_plate("   ") == ""

    def test_corrects_b_read_as_8_in_final_digit_run(self):
        """The B->8 positional OCR correction fires in a digit slot."""
        assert sim.normalise_plate("MH12AB1B34") == "MH12AB1834"

    def test_corrects_multiple_ocr_noise_characters(self):
        """Several positional corrections can be applied in one pass."""
        assert sim.normalise_plate("MH1O2B1234") == "MH1O281234"


# ---------------------------------------------------------------------------
# Frame quality filtering
# ---------------------------------------------------------------------------


class TestFrameQuality:
    """Blur and brightness gating from §7 Flow C step 2."""

    @staticmethod
    def _bgr_gradient() -> np.ndarray:
        """Build a 3-channel linear-gradient test frame."""
        gray = np.tile(
            np.arange(256, dtype=np.uint8).reshape(-1, 1), (1, 64)
        )
        return np.repeat(gray[:, :, None], 3, axis=2)

    def test_sharp_bright_gradient_frame_passes(self):
        """High-texture bright frames are accepted."""
        rng = np.random.default_rng(7)
        texture = rng.integers(0, 256, (128, 128, 3), dtype=np.uint8)
        assert sim.is_frame_usable(texture)

    def test_flat_frame_fails_blur_check(self):
        """Featureless frames are rejected as too blurry."""
        flat = np.full((100, 100, 3), 128, dtype=np.uint8)
        assert not sim.is_frame_usable(flat)

    def test_dark_frame_fails_brightness_check(self):
        """Underexposed frames are rejected for darkening."""
        dark = self._bgr_gradient() // 20
        assert not sim.is_frame_usable(dark)


# ---------------------------------------------------------------------------
# Temporal voting
# ---------------------------------------------------------------------------


class TestTemporalVoter:
    """3-of-5 temporal agreement on OCR reads."""

    def test_requires_min_agreement_before_accepting(self):
        """A plate is only accepted once the threshold is reached."""
        voter = sim.TemporalVoter()
        assert voter.vote(1, "MH12AB1234") is None
        assert voter.vote(1, "MH12AB1234") is None
        assert voter.vote(1, "MH12AB1234") == "MH12AB1234"

    def test_alternating_reads_never_reach_majority(self):
        """Conflicting reads never accumulate to the agreement threshold."""
        voter = sim.TemporalVoter()
        assert voter.vote(1, "MH12AB1234") is None
        assert voter.vote(1, "MH12CD5678") is None
        assert voter.vote(1, "MH12AB1234") is None
        assert voter.vote(1, "MH12CD5678") is None

    def test_trackers_are_isolated(self):
        """Voting windows never leak between different plates."""
        voter = sim.TemporalVoter()
        assert voter.vote(1, "MH12AB1234") is None
        assert voter.vote(2, "MH12CD5678") is None
        assert voter.vote(2, "MH12CD5678") is None
        assert voter.vote(2, "MH12CD5678") == "MH12CD5678"


# ---------------------------------------------------------------------------
# Photo encoding
# ---------------------------------------------------------------------------


class TestEncodeFrameJpeg:
    """Base64 JPEG encoding of a detected hit frame."""

    def test_encodes_frame_as_base64_jpeg(self):
        """A 3-channel frame becomes a decodable base64 JPEG."""
        gray = np.tile(
            np.arange(256, dtype=np.uint8).reshape(-1, 1), (1, 64)
        )
        frame = np.repeat(gray[:, :, None], 3, axis=2)
        encoded = sim.encode_frame_jpeg(frame)
        assert encoded.startswith("/9j/")
        assert base64.b64decode(encoded)[:2] == b"\xff\xd8"


# ---------------------------------------------------------------------------
# Offline queue
# ---------------------------------------------------------------------------


class TestOfflineQueue:
    """SQLite hit queue enqueue/flush behaviour."""

    @staticmethod
    def _enqueue_one(conn, plate="MH12AB1234"):
        """Insert a single representative hit into the caller's queue."""
        sim.queue_hit(
            conn=conn,
            plate=plate,
            lat=19.076,
            lng=72.877,
            captured_at="2026-09-21T12:00:00+00:00",
            confidence=95,
            photo_b64=base64.b64encode(b"\xff\xd8fakejpeg").decode("ascii"),
        )

    def test_queue_roundtrip_flushes_on_200(self, monkeypatch):
        """An accepted hit is deleted from the queue after flush."""

        class FakeResponse:
            """Response stub reporting a 200 acceptance."""

            status_code = 200
            text = ""

        monkeypatch.setattr(
            sim.requests, "post", lambda *a, **k: FakeResponse()
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "queue.db")
            conn = sim.init_offline_db(path)
            self._enqueue_one(conn)

            flushed = sim.flush_queue(conn, "http://localhost:8000", "tok")
            remaining = conn.execute("SELECT COUNT(*) FROM pending_hits").fetchone()[
                0
            ]

            assert flushed == 1
            assert remaining == 0
            conn.close()

    def test_queue_keeps_row_on_server_error(self, monkeypatch):
        """A 5xx response leaves the hit queued for the next flush."""

        class FakeResponse:
            """Response stub reporting a 500 server error."""

            status_code = 500
            text = "boom"

        monkeypatch.setattr(
            sim.requests, "post", lambda *a, **k: FakeResponse()
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "queue.db")
            conn = sim.init_offline_db(path)
            self._enqueue_one(conn)

            flushed = sim.flush_queue(conn, "http://localhost:8000", "tok")
            remaining = conn.execute("SELECT COUNT(*) FROM pending_hits").fetchone()[
                0
            ]

            assert flushed == 0
            assert remaining == 1
            conn.close()

    def test_empty_queue_flushes_nothing(self, monkeypatch):
        """Flushing an empty queue is a no-op, never raising."""
        monkeypatch.setattr(sim.requests, "post", lambda *a, **k: 1 / 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "queue.db")
            conn = sim.init_offline_db(path)
            assert sim.flush_queue(conn, "http://localhost:8000", "tok") == 0
            conn.close()