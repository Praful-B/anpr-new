"""Indian licence plate normalisation and validation tests (§6).

Covers the canonical plate formats, OCR character corrections in the
expected positions, whitespace and case cleanup, and rejection of text
that is not an Indian plate.
"""

import pytest

from app.services.normalizer import is_valid_plate, normalise_plate

# ---------------------------------------------------------------------------
# Canonical plates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plate",
    [
        "MH12AB1234",
        "DL8CAF5030",
        "KA01AB1234",
        "TN10XY9999",
        "GJ01JX0001",
        "UP32KL4321",
        "RJ14CV0002",
        "WB02AD9999",
        "MH01AA0001",
        "AP09XY1234",
    ],
)
def test_canonical_plates_pass_through_unchanged(plate: str) -> None:
    """A well-formed plate is returned unchanged and validates.

    Args:
        plate: A canonical Indian plate string.

    Raises:
        AssertionError: If the plate is altered or rejected.
    """
    assert normalise_plate(plate) == plate
    assert is_valid_plate(plate) is True


# ---------------------------------------------------------------------------
# OCR character corrections
# ---------------------------------------------------------------------------


def test_letter_s_in_digit_position_becomes_five() -> None:
    """A trailing ``S`` read in a digit slot is corrected to ``5``.

    Raises:
        AssertionError: If the correction is not applied.
    """
    assert normalise_plate("MH12AB12S4") == "MH12AB1254"


def test_letter_o_in_digit_position_becomes_zero() -> None:
    """An ``O`` read in a digit slot is corrected to ``0``.

    Raises:
        AssertionError: If the correction is not applied.
    """
    assert normalise_plate("MH12AB1O34") == "MH12AB1034"


def test_letter_i_in_digit_position_becomes_one() -> None:
    """An ``I`` read in a digit slot is corrected to ``1``.

    Raises:
        AssertionError: If the correction is not applied.
    """
    assert normalise_plate("MH12AB123I") == "MH12AB1231"


def test_letter_b_in_digit_position_becomes_eight() -> None:
    """A ``B`` read in a digit slot is corrected to ``8``.

    Raises:
        AssertionError: If the correction is not applied.
    """
    assert normalise_plate("MH12AB1B34") == "MH12AB1834"


def test_letter_z_in_digit_position_becomes_two() -> None:
    """A ``Z`` read in a digit slot is corrected to ``2``.

    Raises:
        AssertionError: If the correction is not applied.
    """
    assert normalise_plate("MH12AB1Z34") == "MH12AB1234"


# ---------------------------------------------------------------------------
# Input cleanup
# ---------------------------------------------------------------------------


def test_whitespace_and_hyphens_are_stripped() -> None:
    """Spaces and hyphens are removed and the plate is uppercased.

    Raises:
        AssertionError: If cleanup does not produce the canonical form.
    """
    assert normalise_plate("MH 12 AB 1234") == "MH12AB1234"
    assert normalise_plate("mh-12-ab-1234") == "MH12AB1234"


def test_lowercase_input_is_uppercased() -> None:
    """Lowercase input normalises to uppercase.

    Raises:
        AssertionError: If the plate is not uppercased.
    """
    assert normalise_plate("ka01ab1234") == "KA01AB1234"


def test_blank_input_raises_value_error() -> None:
    """A blank plate string is rejected outright.

    Raises:
        AssertionError: If no ValueError is raised.
    """
    with pytest.raises(ValueError):
        normalise_plate("   ")


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "MH12AB123A",
        "HELLO",
        "MH12AB1234A",
        "1234567890",
        "AB1234",
    ],
)
def test_non_plates_fail_validation(text: str) -> None:
    """Text that does not fit the Indian pattern fails validation.

    Args:
        text: A non-plate string.

    Raises:
        AssertionError: If the text is wrongly accepted.
    """
    assert is_valid_plate(normalise_plate(text)) is False


def test_empty_string_is_not_a_valid_plate() -> None:
    """The empty string never validates.

    Raises:
        AssertionError: If the empty string validates.
    """
    assert is_valid_plate("") is False
