/**
 * @module Scanner
 * Core scanning screen — runs the camera preview and on-device plate
 * detection loop at 1 Hz (Flow C of §7) and delivers the volunteer hit UX.
 *
 * Per frame:
 *   1. Grab a frame from expo-camera
 *   2. Resize and compress it
 *   3. Run inference (on-device when available, backend fallback otherwise)
 *   4. Normalise the plate (§6)
 *   5. Temporal voting — accept after agreeing reads
 *   6. Match against the in-memory hotlist
 *   7. On match: red banner + hit card + haptic + enqueue + immediate send
 *   8. On no match: DISCARD — no storage, no transmission, no UI change
 *
 * While a matched vehicle stays in view, a location update is enqueued every
 * five seconds; the backend throttles accepted hits to one per device+plate
 * per 30 seconds.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImageManipulator from "expo-image-manipulator";
import * as Location from "expo-location";

import { detectPlates, type PlateDetection } from "../ai/inference";
import { isPlateHotlisted, normalisePlate } from "../ai/match";
import { enqueueHit, getQueueSize, submitQueuedHit } from "../services/queue";
import type { HitDeliveryStatus } from "../services/queue";
import {
  getHotlistPlates,
  getHotlistVersion,
  getLastSyncAt,
} from "../services/hotlist";
import { ensureDeviceRegistered, clearDevice } from "../services/device";
import { recordHit, updateHitStatus } from "../services/hitHistory";
import HitCard from "../components/HitCard";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Inference loop interval in milliseconds (1 Hz). */
const INFERENCE_INTERVAL_MS = 1000;

/** Maximum width for the captured frame. */
const MAX_FRAME_WIDTH = 1280;

/** JPEG compression quality (0-1). */
const JPEG_QUALITY = 0.7;

/** Number of recent reads kept for temporal voting. */
const TEMPORAL_WINDOW_SIZE = 5;

/** Number of agreeing reads required to accept a plate. */
const TEMPORAL_VOTE_THRESHOLD = 3;

/** Queue flush interval in milliseconds. */
const FLUSH_INTERVAL_MS = 5000;

/** How long the hit card stays on screen unless dismissed (ms). */
const HIT_CARD_VISIBLE_MS = 8000;

/** Minimum gap between location updates for a vehicle still in view (ms). */
const LOCATION_RESEND_INTERVAL_MS = 5000;

/** Interval over which the frames-per-second counter is sampled (ms). */
const FPS_WINDOW_MS = 1000;

/** Accepted plate delimiter shown in the banner. */
const BANNER_PREFIX = "⚠ HOTLIST HIT — ";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Temporal voting state for one tracker id. */
interface TrackerVote {
  /** Recent normalised reads (most recent last). */
  reads: string[];
  /** Whether a hit has already been raised for this tracker. */
  confirmed: boolean;
}

/** The match currently shown in the banner and card. */
interface ActiveHit {
  /** Row id in the recent-hits store. */
  historyId: number;
  /** Matched plate string. */
  plate: string;
  /** Latitude at capture, or null. */
  lat: number | null;
  /** Longitude at capture, or null. */
  lng: number | null;
  /** ISO-8601 UTC capture timestamp. */
  capturedAt: string;
  /** OCR confidence score. */
  confidence: number;
  /** Local file URI of the captured frame. */
  thumbnailUri: string | null;
  /** Current delivery status. */
  status: HitDeliveryStatus;
}

/** Navigation callbacks injected by the root App component. */
export interface ScannerNavigation {
  /** Switch to another screen by name. */
  navigate: (screen: string) => void;
}

/** Props accepted by the Scanner screen. */
interface ScannerProps {
  /** Navigation callbacks for the tab bar. */
  navigation: ScannerNavigation;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Scanner screen — camera preview, detection loop, and hit UX.
 *
 * @param props - Navigation callbacks.
 * @returns The scanner UI.
 */
export default function Scanner(props: ScannerProps): React.JSX.Element {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [status, setStatus] = useState<string>("Ready");
  const [fps, setFps] = useState(0);
  const [detectionCount, setDetectionCount] = useState(0);
  const [hotlistVersion, setHotlistVersion] = useState(0);
  const [lastSyncAt, setLastSyncAt] = useState(0);
  const [queueCount, setQueueCount] = useState(0);
  const [activeHit, setActiveHit] = useState<ActiveHit | null>(null);
  const [bannerVisible, setBannerVisible] = useState(false);

  const cameraRef = useRef<CameraView | null>(null);
  const trackerVotes = useRef<Map<string, TrackerVote>>(new Map());
  const inferenceTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const flushTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fpsTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const framesThisSecond = useRef(0);
  const currentLocation = useRef<{ lat: number; lng: number } | null>(null);
  const lastResendAt = useRef<Map<string, number>>(new Map());
  const isProcessing = useRef(false);
  const deviceTokenRef = useRef<string | null>(null);
  const hotlistRef = useRef<ReadonlySet<string>>(new Set<string>());

  // -----------------------------------------------------------------------
  // Location
  // -----------------------------------------------------------------------

  const startLocationTracking = useCallback(async (): Promise<void> => {
    const { status: locStatus } =
      await Location.requestForegroundPermissionsAsync();
    if (locStatus !== "granted") {
      setStatus("Location denied — hits will lack coordinates");
      return;
    }
    await Location.watchPositionAsync(
      { accuracy: Location.Accuracy.Balanced, distanceInterval: 10 },
      (position) => {
        currentLocation.current = {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        };
      }
    );
  }, []);

  // -----------------------------------------------------------------------
  // Device registration
  // -----------------------------------------------------------------------

  const registerDevice = useCallback(async (): Promise<void> => {
    try {
      deviceTokenRef.current = await ensureDeviceRegistered();
    } catch {
      deviceTokenRef.current = null;
      setStatus("Device not registered — hits will queue offline");
    }
  }, []);

  // -----------------------------------------------------------------------
  // Hit delivery
  // -----------------------------------------------------------------------

  const deliverHit = useCallback(
    async (historyId: number, queueId: number): Promise<void> => {
      const token = deviceTokenRef.current;
      if (!token) {
        await updateHitStatus(historyId, "queued");
        setActiveHit((prev) =>
          prev && prev.historyId === historyId
            ? { ...prev, status: "queued" }
            : prev
        );
        return;
      }

      const deliveryStatus = await submitQueuedHit(queueId, token);
      await updateHitStatus(historyId, deliveryStatus);
      setActiveHit((prev) =>
        prev && prev.historyId === historyId
          ? { ...prev, status: deliveryStatus }
          : prev
      );
    },
    []
  );

  const raiseHit = useCallback(
    async (
      detection: PlateDetection,
      frameBase64: string,
      thumbnailUri: string | null
    ): Promise<void> => {
      const capturedAt = new Date().toISOString();
      const lat = currentLocation.current?.lat ?? null;
      const lng = currentLocation.current?.lng ?? null;

      await Haptics.notificationAsync(
        Haptics.NotificationFeedbackType.Success
      );

      const historyId = await recordHit({
        plate: detection.plate,
        lat,
        lng,
        captured_at: capturedAt,
        confidence: detection.confidence,
        status: "sending",
        thumbnail_uri: thumbnailUri,
      });

      setActiveHit({
        historyId,
        plate: detection.plate,
        lat,
        lng,
        capturedAt,
        confidence: detection.confidence,
        thumbnailUri,
        status: "sending",
      });
      setBannerVisible(true);

      const queueId = await enqueueHit({
        plate: detection.plate,
        lat: lat ?? 0,
        lng: lng ?? 0,
        captured_at: capturedAt,
        confidence: detection.confidence,
        photo_b64: frameBase64,
      });

      await deliverHit(historyId, queueId);
      setQueueCount(await getQueueSize());
    },
    [deliverHit]
  );

  const enqueueLocationUpdate = useCallback(
    async (plate: string, frameBase64: string, confidence: number) => {
      const lat = currentLocation.current?.lat ?? 0;
      const lng = currentLocation.current?.lng ?? 0;
      await enqueueHit({
        plate,
        lat,
        lng,
        captured_at: new Date().toISOString(),
        confidence,
        photo_b64: frameBase64,
      });
      lastResendAt.current.set(plate, Date.now());
    },
    []
  );

  // -----------------------------------------------------------------------
  // Detection handling
  // -----------------------------------------------------------------------

  const handleMatch = useCallback(
    async (
      plate: string,
      detection: PlateDetection,
      frameBase64: string,
      thumbnailUri: string | null
    ): Promise<void> => {
      setStatus(`HIT: ${plate}`);
      await raiseHit(
        { ...detection, plate },
        frameBase64,
        thumbnailUri
      );
    },
    [raiseHit]
  );

  const handleDetection = useCallback(
    async (
      detection: PlateDetection,
      frameBase64: string,
      thumbnailUri: string | null
    ): Promise<void> => {
      const normalised = normalisePlate(detection.plate);
      if (!normalised) return;

      const existing = trackerVotes.current.get(normalised);
      if (existing) {
        existing.reads.push(normalised);
        if (existing.reads.length > TEMPORAL_WINDOW_SIZE) {
          existing.reads.shift();
        }
      } else {
        trackerVotes.current.set(normalised, {
          reads: [normalised],
          confirmed: false,
        });
      }

      const vote = trackerVotes.current.get(normalised);
      if (!vote) return;

      const agreeing = vote.reads.filter((read) => read === normalised).length;
      if (agreeing < TEMPORAL_VOTE_THRESHOLD) return;

      if (!vote.confirmed) {
        vote.confirmed = true;
        if (isPlateHotlisted(normalised, hotlistRef.current)) {
          await handleMatch(normalised, detection, frameBase64, thumbnailUri);
        }
        return;
      }

      const lastResend = lastResendAt.current.get(normalised) ?? 0;
      if (Date.now() - lastResend >= LOCATION_RESEND_INTERVAL_MS) {
        await enqueueLocationUpdate(normalised, frameBase64, detection.confidence);
      }
    },
    [handleMatch, enqueueLocationUpdate]
  );

  // -----------------------------------------------------------------------
  // Frame capture and processing
  // -----------------------------------------------------------------------

  const captureFrame = useCallback(
    async (): Promise<{ base64: string; uri: string } | null> => {
      if (!cameraRef.current) return null;
      const photo = await cameraRef.current.takePictureAsync({
        quality: JPEG_QUALITY,
        skipProcessing: true,
      });
      if (!photo?.uri) return null;

      const manipulated = await ImageManipulator.manipulateAsync(
        photo.uri,
        [{ resize: { width: MAX_FRAME_WIDTH } }],
        { compress: JPEG_QUALITY, format: ImageManipulator.SaveFormat.JPEG }
      );

      const response = await fetch(manipulated.uri);
      const blob = await response.blob();
      const buffer = await blob.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = "";
      for (let index = 0; index < bytes.length; index += 1) {
        binary += String.fromCharCode(bytes[index] ?? 0);
      }
      return { base64: btoa(binary), uri: manipulated.uri };
    },
    []
  );

  const processFrame = useCallback(async (): Promise<void> => {
    if (isProcessing.current) return;
    isProcessing.current = true;
    try {
      const frame = await captureFrame();
      if (!frame) return;

      framesThisSecond.current += 1;
      const detections = await detectPlates(frame.base64);
      if (detections.length > 0) {
        setDetectionCount((prev) => prev + detections.length);
      }

      for (const detection of detections) {
        await handleDetection(detection, frame.base64, frame.uri);
      }

      setHotlistVersion(getHotlistVersion());
      setLastSyncAt(getLastSyncAt());
    } catch {
      // Frame errors are expected; the next tick retries.
    } finally {
      isProcessing.current = false;
    }
  }, [captureFrame, handleDetection]);

  // -----------------------------------------------------------------------
  // Loops
  // -----------------------------------------------------------------------

  const flushHitQueue = useCallback(async (): Promise<void> => {
    const token = deviceTokenRef.current;
    if (!token) return;
    setQueueCount(await getQueueSize());
  }, []);

  const startLoops = useCallback((): void => {
    inferenceTimer.current = setInterval(processFrame, INFERENCE_INTERVAL_MS);
    flushTimer.current = setInterval(flushHitQueue, FLUSH_INTERVAL_MS);
    fpsTimer.current = setInterval(() => {
      setFps(framesThisSecond.current);
      framesThisSecond.current = 0;
    }, FPS_WINDOW_MS);
  }, [processFrame, flushHitQueue]);

  const stopLoops = useCallback((): void => {
    for (const timer of [inferenceTimer, flushTimer, fpsTimer]) {
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
    }
  }, []);

  const cancelBannerTimer = useCallback((): void => {
    if (bannerTimer.current) {
      clearTimeout(bannerTimer.current);
      bannerTimer.current = null;
    }
  }, []);

  const dismissHitCard = useCallback((): void => {
    cancelBannerTimer();
    setBannerVisible(false);
    setActiveHit(null);
  }, [cancelBannerTimer]);

  const toggleScanning = useCallback((): void => {
    if (scanning) {
      stopLoops();
      setScanning(false);
      setStatus("Paused");
    } else {
      startLoops();
      setScanning(true);
      setStatus("Scanning...");
    }
  }, [scanning, startLoops, stopLoops]);

  const handleRevocation = useCallback(async (): Promise<void> => {
    await clearDevice();
    deviceTokenRef.current = null;
    setHotlistVersion(0);
    setStatus("Device revoked — rescan required");
  }, []);

  // -----------------------------------------------------------------------
  // Lifecycle
  // -----------------------------------------------------------------------

  useEffect(() => {
    startLocationTracking();
    registerDevice();
    return () => {
      stopLoops();
      cancelBannerTimer();
    };
  }, [startLocationTracking, registerDevice, stopLoops, cancelBannerTimer]);

  useEffect(() => {
    if (!bannerVisible) return undefined;
    bannerTimer.current = setTimeout(dismissHitCard, HIT_CARD_VISIBLE_MS);
    return () => cancelBannerTimer();
  }, [bannerVisible, dismissHitCard, cancelBannerTimer]);

  useEffect(() => {
    hotlistRef.current = new Set(getHotlistPlates());
  }, [hotlistVersion]);

  // -----------------------------------------------------------------------
  // Permission gates
  // -----------------------------------------------------------------------

  if (!permission) {
    return (
      <View style={styles.centered}>
        <Text style={styles.permissionText}>Requesting camera permission...</Text>
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.centered}>
        <Text style={styles.permissionText}>
          Camera permission is required for plate scanning.
        </Text>
        <TouchableOpacity
          style={styles.permissionButton}
          onPress={requestPermission}
        >
          <Text style={styles.permissionButtonText}>Grant Permission</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => props.navigation.navigate("History")}>
          <Text style={styles.linkText}>View Recent Hits</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  const syncLabel =
    lastSyncAt > 0
      ? new Date(lastSyncAt).toLocaleTimeString("en-IN")
      : "never";

  return (
    <View style={styles.container}>
      <CameraView ref={cameraRef} style={styles.camera} facing="back" />

      <View style={styles.overlay} pointerEvents="box-none">
        {bannerVisible && activeHit ? (
          <View testID="hotlist-banner" style={styles.banner}>
            <Text style={styles.bannerText}>
              {BANNER_PREFIX}
              {activeHit.plate}
            </Text>
          </View>
        ) : null}

        <View style={styles.infoStrip}>
          <Text style={styles.infoText}>FPS {fps}</Text>
          <Text style={styles.infoText}>Det {detectionCount}</Text>
          <Text style={styles.infoText}>Hotlist v{hotlistVersion}</Text>
          <Text style={styles.infoText}>Sync {syncLabel}</Text>
          <Text style={styles.infoText}>Queue {queueCount}</Text>
        </View>

        <View style={styles.spacer} pointerEvents="none" />

        <View style={styles.controls}>
          <Text style={styles.statusText}>{status}</Text>
          <TouchableOpacity
            style={[styles.scanButton, scanning && styles.scanButtonActive]}
            onPress={toggleScanning}
          >
            <Text style={styles.scanButtonText}>
              {scanning ? "Pause" : "Start Scanning"}
            </Text>
          </TouchableOpacity>
          <View style={styles.tabBar}>
            <TouchableOpacity onPress={() => props.navigation.navigate("History")}>
              <Text style={styles.tabText}>Recent Hits</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => props.navigation.navigate("CitizenComplaint")}
            >
              <Text style={styles.tabText}>My Complaints</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={handleRevocation}>
              <Text style={styles.tabText}>Sign Out</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>

      {activeHit ? (
        <HitCard
          plate={activeHit.plate}
          lat={activeHit.lat}
          lng={activeHit.lng}
          capturedAt={activeHit.capturedAt}
          confidence={activeHit.confidence}
          status={activeHit.status}
          thumbnailUri={activeHit.thumbnailUri}
          onDismiss={dismissHitCard}
        />
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  camera: { flex: 1 },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#1a1a2e",
    paddingHorizontal: 32,
  },
  overlay: { ...StyleSheet.absoluteFillObject },
  banner: {
    backgroundColor: "#d9534f",
    paddingVertical: 18,
    paddingHorizontal: 16,
  },
  bannerText: {
    color: "#fff",
    fontSize: 20,
    fontWeight: "bold",
    letterSpacing: 1,
  },
  infoStrip: {
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  infoText: { color: "#e6e6e6", fontSize: 11 },
  spacer: { flex: 1 },
  controls: { padding: 16 },
  statusText: { color: "#fff", fontSize: 14, marginBottom: 8 },
  scanButton: {
    backgroundColor: "#e94560",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
  },
  scanButtonActive: { backgroundColor: "#5cb85c" },
  scanButtonText: { color: "#fff", fontSize: 18, fontWeight: "bold" },
  tabBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 12,
  },
  tabText: { color: "#8fb8ff", fontSize: 14, fontWeight: "600" },
  permissionText: {
    color: "#fff",
    fontSize: 16,
    textAlign: "center",
    marginBottom: 16,
  },
  permissionButton: {
    backgroundColor: "#e94560",
    borderRadius: 8,
    paddingHorizontal: 24,
    paddingVertical: 12,
  },
  permissionButtonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  linkText: { color: "#8fb8ff", fontSize: 14, marginTop: 16 },
});
