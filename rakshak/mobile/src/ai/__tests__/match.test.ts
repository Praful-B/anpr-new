/**
 * Unit tests for the pure plate-normalisation and hotlist-matching logic.
 *
 * Mirrors the backend normaliser's behaviour (see
 * backend/tests/test_plate_regex.py) so a plate accepted on-device is
 * accepted server-side and vice versa.
 */

import {
  buildHotlistSet,
  isPlateHotlisted,
  isValidPlate,
  normalisePlate,
  normaliseTwoLinePlate,
} from "../match";

// ---------------------------------------------------------------------------
// Canonical plates
// ---------------------------------------------------------------------------

describe("normalisePlate — canonical plates", () => {
  it("accepts MH12AB1234 unchanged", () => {
    expect(normalisePlate("MH12AB1234")).toBe("MH12AB1234");
  });

  it("accepts DL8CAF5030 unchanged", () => {
    expect(normalisePlate("DL8CAF5030")).toBe("DL8CAF5030");
  });

  it("accepts KA01AB1234 unchanged", () => {
    expect(normalisePlate("KA01AB1234")).toBe("KA01AB1234");
  });

  it("accepts TN10XY9999 unchanged", () => {
    expect(normalisePlate("TN10XY9999")).toBe("TN10XY9999");
  });
});

// ---------------------------------------------------------------------------
// OCR error correction
// ---------------------------------------------------------------------------

describe("normalisePlate — OCR character corrections", () => {
  it("corrects S to 5 in a digit position", () => {
    expect(normalisePlate("MH12AB12S4")).toBe("MH12AB1254");
  });

  it("corrects O to 0 in a digit position", () => {
    expect(normalisePlate("MH12AB1O34")).toBe("MH12AB1034");
  });

  it("corrects I to 1 in a digit position", () => {
    expect(normalisePlate("MH12AB123I")).toBe("MH12AB1231");
  });

  it("corrects B to 8 in a digit position", () => {
    expect(normalisePlate("MH12AB1B34")).toBe("MH12AB1834");
  });

  it("corrects Z to 2 in a digit position", () => {
    expect(normalisePlate("MH12AB1Z34")).toBe("MH12AB1234");
  });
});

// ---------------------------------------------------------------------------
// Input cleanup
// ---------------------------------------------------------------------------

describe("normalisePlate — input cleanup", () => {
  it("strips spaces and hyphens and uppercases", () => {
    expect(normalisePlate(" mh 12-ab 1234 ")).toBe("MH12AB1234");
  });

  it("normalises lowercase input", () => {
    expect(normalisePlate("ka01ab1234")).toBe("KA01AB1234");
  });
});

// ---------------------------------------------------------------------------
// Invalid input
// ---------------------------------------------------------------------------

describe("normalisePlate — invalid input", () => {
  it("returns an empty string for blank input", () => {
    expect(normalisePlate("")).toBe("");
    expect(normalisePlate("   ")).toBe("");
  });

  it("rejects a plate ending in a letter", () => {
    expect(isValidPlate(normalisePlate("MH12AB123A"))).toBe(false);
  });

  it("rejects plate text that is too long", () => {
    expect(isValidPlate(normalisePlate("MH12AB1234A"))).toBe(false);
  });

  it("rejects non-plate words", () => {
    expect(isValidPlate(normalisePlate("HELLO"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Two-line plates
// ---------------------------------------------------------------------------

describe("normaliseTwoLinePlate", () => {
  it("joins two OCR lines into one valid plate", () => {
    expect(normaliseTwoLinePlate("MH12", "AB1234")).toBe("MH12AB1234");
  });

  it("returns an empty string when the joined value is invalid", () => {
    expect(normaliseTwoLinePlate("HELLO", "WORLD")).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Hotlist matching
// ---------------------------------------------------------------------------

describe("hotlist matching", () => {
  it("matches an exact hotlisted plate", () => {
    const hotlist = buildHotlistSet(["MH12AB1234"]);
    expect(isPlateHotlisted("MH12AB1234", hotlist)).toBe(true);
  });

  it("matches a hotlisted plate despite OCR noise", () => {
    const hotlist = buildHotlistSet(["MH12AB1234"]);
    expect(isPlateHotlisted("MH12AB1Z34", hotlist)).toBe(true);
    expect(isPlateHotlisted(" mh12 ab 1234 ", hotlist)).toBe(true);
  });

  it("does not match a plate that is absent from the hotlist", () => {
    const hotlist = buildHotlistSet(["MH12AB1234"]);
    expect(isPlateHotlisted("KA01AB1234", hotlist)).toBe(false);
  });

  it("never matches an invalid plate even if it is in the set", () => {
    const hotlist = buildHotlistSet(["NOTAPLATE"]);
    expect(isPlateHotlisted("NOTAPLATE", hotlist)).toBe(false);
  });

  it("returns false for an empty hotlist", () => {
    expect(isPlateHotlisted("MH12AB1234", buildHotlistSet([]))).toBe(false);
  });
});
