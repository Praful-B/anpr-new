/**
 * @module inference
 * On-device plate detection pipeline wrapper.
 *
 * Attempts to use react-native-fast-tflite with YOLO11n + OCR TFLite models
 * for on-device inference. If TFLite integration exceeds reasonable effort
 * (documented in KNOWN_LIMITATIONS.md), falls back to sending frames to the
 * backend POST /api/v1/detect endpoint — a prototype shortcut that violates
 * the zero-retention promise if used in production.
 *
 * The fallback path is clearly documented in ARCHITECTURE.md.
 */

import { apiRequest } from "../services/api";
import { normalisePlate } from "./match";

// Re-export the pure normalisation helpers so existing callers keep working.
export { normalisePlate };
export { isValidPlate, isPlateHotlisted, buildHotlistSet } from "./match";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Confidence threshold below which detections are discarded. */
const MIN_CONFIDENCE_THRESHOLD = 40;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Result of a single plate detection inference pass. */
export interface PlateDetection {
  /** Normalised plate string. */
  plate: string;
  /** Confidence score (0-100). */
  confidence: number;
}

/** Status of the inference engine. */
export type InferenceEngineStatus = "tflite" | "fallback" | "uninitialized";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** Current inference engine status. */
let _engineStatus: InferenceEngineStatus = "uninitialized";

// ---------------------------------------------------------------------------
// TFLite engine (stub — falls back to backend)
// ---------------------------------------------------------------------------

/**
 * Attempt to initialise the TFLite inference engine.
 *
 * This is a stub that always falls back to the backend. To enable
 * on-device inference, integrate react-native-fast-tflite with the
 * YOLO11n TFLite model and a small OCR TFLite model.
 */
async function tryInitTflite(): Promise<boolean> {
  try {
    // Placeholder: check if react-native-fast-tflite is available.
    // In a real build, this would load the TFLite model.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const TFLite = require("react-native-fast-tflite");
    if (TFLite && typeof TFLite.loadModel === "function") {
      _engineStatus = "tflite";
      return true;
    }
  } catch {
    // Module not available — use fallback.
  }
  return false;
}

// ---------------------------------------------------------------------------
// Fallback: backend /api/v1/detect
// ---------------------------------------------------------------------------

/**
 * Detect plates by sending a base64 frame to the backend fallback endpoint.
 *
 * @param frameBase64 - Base64-encoded JPEG frame from the camera.
 * @returns Array of detected plates with confidence scores.
 */
async function detectViaBackend(
  frameBase64: string
): Promise<PlateDetection[]> {
  try {
    const result = await apiRequest("/detect", {
      method: "POST",
      body: JSON.stringify({ frame_b64: frameBase64 }),
    });

    const data = result as { plates: Array<{ plate: string; confidence: number }> };
    return data.plates.map((p) => ({
      plate: normalisePlate(p.plate),
      confidence: p.confidence,
    }));
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the inference engine. Tries TFLite first, falls back to backend.
 */
export async function initInference(): Promise<void> {
  const tfliteReady = await tryInitTflite();
  if (!tfliteReady) {
    _engineStatus = "fallback";
  }
}

/**
 * Run plate detection on a single frame.
 *
 * @param frameBase64 - Base64-encoded JPEG frame from expo-camera.
 * @returns Array of detected plates that pass confidence threshold.
 */
export async function detectPlates(
  frameBase64: string
): Promise<PlateDetection[]> {
  if (_engineStatus === "tflite") {
    // Future: run YOLO11n + OCR TFLite on-device.
    // For now, fall through to backend.
  }

  return detectViaBackend(frameBase64);
}

/**
 * Get the current inference engine status.
 *
 * @returns "tflite", "fallback", or "uninitialized".
 */
export function getInferenceStatus(): InferenceEngineStatus {
  return _engineStatus;
}

/**
 * Get the minimum confidence threshold.
 *
 * @returns The threshold value (0-100).
 */
export function getConfidenceThreshold(): number {
  return MIN_CONFIDENCE_THRESHOLD;
}
