/**
 * Unit tests for the offline-hit queue's delivery classification.
 *
 * Verifies that the batch ingest response from the backend
 * ({accepted, dropped, reasons: [{index, reason}]}) is classified into
 * the single-event delivery statuses surfaced by the scanner UI.
 */

import { classifyDelivery } from "../queue";

jest.mock("expo-sqlite", () => ({}));
jest.mock("../api", () => ({
  deviceApiRequest: jest.fn(),
  ApiError: class ApiError extends Error {},
}));

describe("classifyDelivery", () => {
  it("returns sent when the batch accepted at least one event", () => {
    expect(classifyDelivery(1, [])).toBe("sent");
  });

  it("returns throttled when a drop reason is throttled", () => {
    expect(classifyDelivery(0, [{ index: 0, reason: "throttled" }])).toBe(
      "throttled"
    );
  });

  it("returns rejected for other drop reasons", () => {
    expect(
      classifyDelivery(0, [{ index: 0, reason: "plate_not_hotlisted" }])
    ).toBe("rejected");
  });

  it("never misclassifies a throttled event as rejected", () => {
    const outcome = classifyDelivery(0, [
      { index: 0, reason: "plate_not_hotlisted" },
      { index: 1, reason: "throttled" },
    ]);
    expect(outcome).toBe("throttled");
  });
});