/**
 * @module match
 * Pure plate-normalisation and hotlist-matching logic (§6 and §8).
 *
 * This module is intentionally free of React Native, Expo, and network
 * dependencies so it can be unit-tested in a plain Node environment with Jest.
 * It is the single source of truth for turning raw OCR text into a canonical
 * Indian plate string and for deciding whether that plate is hotlisted.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Minimum length of a canonical Indian plate. */
export const MIN_PLATE_LENGTH = 6;

/** Number of leading alpha characters in the state code. */
export const STATE_CODE_LENGTH = 2;

/** Number of trailing digits in the registration number. */
export const TRAILING_DIGIT_COUNT = 4;

/** Canonical Indian plate pattern: 2 alpha, 1-2 digits, 1-3 alpha, 4 digits. */
export const INDIAN_PLATE_PATTERN = /^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$/;

/** Characters stripped from raw OCR text before normalisation. */
const SEPARATOR_PATTERN = /[\s\-]/g;

/** OCR misreads corrected when a digit is expected. */
export const DIGIT_CORRECTIONS: Readonly<Record<string, string>> = {
  O: "0",
  I: "1",
  B: "8",
  S: "5",
  Z: "2",
};

/** OCR misreads corrected when a letter is expected. */
export const ALPHA_CORRECTIONS: Readonly<Record<string, string>> = {
  "0": "O",
  "1": "I",
};

/** Expected character classes used when walking a plate left to right. */
export type CharType = "alpha" | "digit" | "unknown";

// ---------------------------------------------------------------------------
// Structure inference
// ---------------------------------------------------------------------------

/**
 * Find the index where the RTO digit code ends.
 *
 * @param chars - Characters of the uppercased, separator-free plate.
 * @returns Index of the first letter after position 1, or a default.
 */
function findRtoEnd(chars: readonly string[]): number {
  for (let index = STATE_CODE_LENGTH; index < chars.length; index += 1) {
    const char = chars[index];
    if (char !== undefined && /[A-Z]/.test(char)) {
      return index;
    }
  }
  return Math.min(STATE_CODE_LENGTH + 2, chars.length);
}

/**
 * Find the index where the alpha series code ends.
 *
 * @param chars - Characters of the plate.
 * @param seriesStart - Index where the series code begins.
 * @returns Index of the first digit after the series, or a default.
 */
function findSeriesEnd(chars: readonly string[], seriesStart: number): number {
  for (let index = seriesStart; index < chars.length; index += 1) {
    const char = chars[index];
    if (char !== undefined && /[0-9]/.test(char)) {
      return index;
    }
  }
  return Math.max(0, chars.length - TRAILING_DIGIT_COUNT);
}

/**
 * Infer the expected character class at every position of a plate.
 *
 * @param chars - Characters of the uppercased, separator-free plate.
 * @returns Array of expected classes, one per position.
 */
export function inferPlateStructure(chars: readonly string[]): CharType[] {
  const total = chars.length;
  const structure: CharType[] = ["alpha", "alpha"];
  for (let index = STATE_CODE_LENGTH; index < total; index += 1) {
    structure.push("unknown");
  }

  const rtoEnd = findRtoEnd(chars);
  const seriesEnd = findSeriesEnd(chars, rtoEnd);

  for (let index = rtoEnd; index < seriesEnd && index < total; index += 1) {
    structure[index] = "alpha";
  }
  for (let index = seriesEnd; index < total; index += 1) {
    structure[index] = "digit";
  }
  for (let index = STATE_CODE_LENGTH; index < rtoEnd; index += 1) {
    structure[index] = "digit";
  }

  return structure;
}

/**
 * Correct a single OCR character given the class expected at its position.
 *
 * @param char - The character read by OCR.
 * @param expected - The expected character class at this position.
 * @returns The corrected character, or the input when no rule applies.
 */
export function correctCharacter(char: string, expected: CharType): string {
  if (expected === "digit" && char in DIGIT_CORRECTIONS) {
    return DIGIT_CORRECTIONS[char] ?? char;
  }
  if (expected === "alpha" && char in ALPHA_CORRECTIONS) {
    return ALPHA_CORRECTIONS[char] ?? char;
  }
  return char;
}

// ---------------------------------------------------------------------------
// Public normalisation API
// ---------------------------------------------------------------------------

/**
 * Normalise a raw OCR plate string to the canonical Indian format.
 *
 * Uppercases the input, strips separators, then applies positional OCR
 * corrections based on the Indian plate structure. Returns an empty string
 * when the input is blank; otherwise returns the best-effort normalisation
 * (use {@link isValidPlate} to check whether it is a real plate).
 *
 * @param rawPlate - The raw plate string from OCR.
 * @returns The normalised plate string, or "" when the input is blank.
 */
export function normalisePlate(rawPlate: string): string {
  if (!rawPlate || !rawPlate.trim()) {
    return "";
  }

  const stripped = rawPlate.toUpperCase().replace(SEPARATOR_PATTERN, "");
  if (INDIAN_PLATE_PATTERN.test(stripped)) {
    return stripped;
  }
  if (stripped.length < MIN_PLATE_LENGTH) {
    return stripped;
  }

  const structure = inferPlateStructure(stripped.split(""));
  return stripped
    .split("")
    .map((char, index) => {
      const expected = structure[index];
      return expected === undefined ? char : correctCharacter(char, expected);
    })
    .join("");
}

/**
 * Normalise a two-line plate captured as separate top and bottom crops.
 *
 * @param topLine - Raw OCR text from the upper half of the plate.
 * @param bottomLine - Raw OCR text from the lower half of the plate.
 * @returns The normalised plate, or "" when the result is not a valid plate.
 */
export function normaliseTwoLinePlate(
  topLine: string,
  bottomLine: string
): string {
  const combined = normalisePlate(`${topLine}${bottomLine}`);
  return isValidPlate(combined) ? combined : "";
}

/**
 * Check whether a normalised plate matches the canonical Indian pattern.
 *
 * @param plate - A normalised plate string.
 * @returns True when the plate matches the expected pattern.
 */
export function isValidPlate(plate: string): boolean {
  return INDIAN_PLATE_PATTERN.test(plate);
}

// ---------------------------------------------------------------------------
// Matching API
// ---------------------------------------------------------------------------

/**
 * Build an O(1) lookup set from the decrypted hotlist plate strings.
 *
 * @param plates - Normalised plate strings from the decrypted hotlist.
 * @returns A set of normalised plates for constant-time membership tests.
 */
export function buildHotlistSet(plates: readonly string[]): Set<string> {
  return new Set(plates);
}

/**
 * Decide whether a scanned plate is on the hotlist.
 *
 * The scanned value is normalised first, so OCR misreads of a hotlisted plate
 * still match. Plates that fail the Indian pattern are never considered a hit.
 *
 * @param scannedPlate - Raw or normalised plate string from the scan.
 * @param hotlist - The in-memory hotlist set.
 * @returns True when the normalised scanned plate is present in the hotlist.
 */
export function isPlateHotlisted(
  scannedPlate: string,
  hotlist: ReadonlySet<string>
): boolean {
  const normalised = normalisePlate(scannedPlate);
  if (!isValidPlate(normalised)) {
    return false;
  }
  return hotlist.has(normalised);
}
