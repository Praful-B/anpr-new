"""Indian licence plate normalisation — server-side cleanup.

Implements the server-side normalisation described in §8 of PROJECT_INFO.md:
uppercasing, space/hyphen stripping, and positional OCR error correction for
common misreads (O→0, I→1, B→8, S→5, Z→2 in digit positions; 0→O, 1→I
in alpha positions). Validates against the Indian plate pattern.
"""

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RAW_PLATE_STRIP_RE = re.compile(r"[\s\-]")
INDIAN_PLATE_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")

MIN_PLATE_LENGTH = 6
STATE_CODE_LENGTH = 2
TRAILING_DIGIT_COUNT = 4

CHAR_TYPE_ALPHA = "alpha"
CHAR_TYPE_DIGIT = "digit"
CHAR_TYPE_UNKNOWN = "unknown"

DIGIT_CORRECTIONS = {"O": "0", "I": "1", "B": "8", "S": "5", "Z": "2"}
ALPHA_CORRECTIONS = {"0": "O", "1": "I"}


def normalise_plate(raw_plate: str) -> str:
    """Normalise a raw OCR plate string to the canonical Indian format.

    Steps:
        1. Uppercase and strip whitespace/hyphens.
        2. Apply positional OCR corrections based on the Indian plate
           structure (state code alpha, RTO digits, series alpha, number digits).

    Args:
        raw_plate: The raw plate string from OCR.

    Returns:
        str: The normalised plate string.

    Raises:
        ValueError: If the raw plate is empty after stripping.
    """
    if not raw_plate or not raw_plate.strip():
        raise ValueError("Plate string must not be empty")

    normalised = _RAW_PLATE_STRIP_RE.sub("", raw_plate.upper())
    return _apply_positional_corrections(normalised)


def _correct_character(character: str, expected_type: str) -> str:
    """Correct a single character given its expected type.

    Args:
        character: The character read by OCR.
        expected_type: One of ``alpha``, ``digit`` or ``unknown``.

    Returns:
        str: The corrected character, or the input when no rule applies.
    """
    if expected_type == CHAR_TYPE_DIGIT and character in DIGIT_CORRECTIONS:
        return DIGIT_CORRECTIONS[character]
    if expected_type == CHAR_TYPE_ALPHA and character in ALPHA_CORRECTIONS:
        return ALPHA_CORRECTIONS[character]
    return character


def _apply_positional_corrections(plate: str) -> str:
    """Apply positional OCR corrections based on Indian plate structure.

    The Indian plate format is: ``^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$``

    - Positions 0-1: state code (alpha expected)
    - Positions 2-3 (or 2-4): RTO code (digits expected)
    - Middle segment: series code (alpha expected)
    - Trailing 4 characters: number (digits expected)

    First attempts to match the pattern directly. If it already matches,
    returns unchanged. Otherwise walks the string and applies corrections
    based on the expected type at each position.

    Args:
        plate: Uppercased plate string with spaces/hyphens removed.

    Returns:
        str: Plate with positional OCR corrections applied.
    """
    if INDIAN_PLATE_PATTERN.match(plate):
        return plate

    characters = list(plate)
    if len(characters) < MIN_PLATE_LENGTH:
        return plate

    structure = _infer_plate_structure(characters)
    for index, expected_type in enumerate(structure[: len(characters)]):
        characters[index] = _correct_character(characters[index], expected_type)

    return "".join(characters)


def _infer_plate_structure(chars: list[str]) -> list[str]:
    """Infer the expected character type (digit/alpha) at each position.

    Uses the Indian plate structure: 2 alpha (state) + 1-2 digits (RTO)
    + 1-3 alpha (series) + 4 digits (number). Uses heuristics to find
    the transitions when the plate is not yet perfectly structured.

    Args:
        chars: List of characters from the normalised plate.

    Returns:
        list[str]: List of ``alpha`` or ``digit`` strings, one per
        position. Unknown positions default to ``digit``.
    """
    total = len(chars)
    structure = [CHAR_TYPE_ALPHA] * STATE_CODE_LENGTH + [CHAR_TYPE_UNKNOWN] * max(
        0, total - STATE_CODE_LENGTH
    )

    series_start = _find_rto_end(chars)
    series_end = _find_series_end(chars, series_start)

    for index in range(series_start, min(series_end, total)):
        structure[index] = CHAR_TYPE_ALPHA

    for index in range(series_end, total):
        structure[index] = CHAR_TYPE_DIGIT

    for index in range(STATE_CODE_LENGTH, series_start):
        structure[index] = CHAR_TYPE_DIGIT

    return structure


def _find_rto_end(chars: list[str]) -> int:
    """Find where the RTO digit code ends.

    Scans from position 2 looking for the first alpha character, which
    marks the start of the series code.

    Args:
        chars: List of characters from the normalised plate.

    Returns:
        int: Index where the RTO code ends (first alpha after position 1).
    """
    for index in range(STATE_CODE_LENGTH, len(chars)):
        if chars[index].isalpha():
            return index
    return min(STATE_CODE_LENGTH + 2, len(chars))


def _find_series_end(chars: list[str], series_start: int) -> int:
    """Find where the alpha series code ends.

    Scans from ``series_start`` looking for the first digit, which
    marks the start of the trailing number.

    Args:
        chars: List of characters from the normalised plate.
        series_start: Index where the series code begins.

    Returns:
        int: Index where the series code ends.
    """
    for index in range(series_start, len(chars)):
        if chars[index].isdigit():
            return index
    return max(0, len(chars) - TRAILING_DIGIT_COUNT)


def is_valid_plate(plate: str) -> bool:
    """Check whether a normalised plate matches the expected Indian pattern.

    Pattern: ``^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$``

    Args:
        plate: A normalised plate string.

    Returns:
        bool: True if the plate matches the expected pattern.
    """
    return bool(INDIAN_PLATE_PATTERN.match(plate))
