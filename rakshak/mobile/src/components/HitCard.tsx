/**
 * @module HitCard
 * Slide-up card shown to the volunteer when a scanned plate matches the
 * hotlist. Displays the captured frame thumbnail, plate, confidence, GPS
 * coordinates, timestamp, and the delivery status of the hit.
 */

import React, { useEffect, useRef } from "react";
import {
  Animated,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import type { HitDeliveryStatus } from "../services/queue";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Duration of the slide-up animation in milliseconds. */
const SLIDE_DURATION_MS = 260;

/** Distinct color per delivery status. */
const STATUS_COLORS: Readonly<Record<HitDeliveryStatus, string>> = {
  sending: "#f0ad4e",
  sent: "#5cb85c",
  throttled: "#f0ad4e",
  rejected: "#d9534f",
  queued: "#5bc0de",
};

/** Human-readable label per delivery status. */
const STATUS_LABELS: Readonly<Record<HitDeliveryStatus, string>> = {
  sending: "Sending...",
  sent: "Sent ✓",
  throttled: "Throttled",
  rejected: "Rejected",
  queued: "Queued (offline)",
};

/** Number of decimal places used when rendering GPS coordinates. */
const COORDINATE_DECIMALS = 6;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Props accepted by {@link HitCard}. */
export interface HitCardProps {
  /** The plate string that matched the hotlist. */
  plate: string;
  /** Latitude of the capture, or null when location was unavailable. */
  lat: number | null;
  /** Longitude of the capture, or null when location was unavailable. */
  lng: number | null;
  /** ISO-8601 UTC capture timestamp. */
  capturedAt: string;
  /** OCR confidence score (0-100). */
  confidence: number;
  /** Current delivery status of the hit. */
  status: HitDeliveryStatus;
  /** Local file URI of the captured frame, if any. */
  thumbnailUri: string | null;
  /** Called when the volunteer dismisses the card. */
  onDismiss: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format a coordinate pair for display.
 *
 * @param lat - Latitude, or null.
 * @param lng - Longitude, or null.
 * @returns A "lat, lng" string with fixed precision, or a placeholder.
 */
function formatCoordinates(lat: number | null, lng: number | null): string {
  if (lat === null || lng === null) {
    return "Location unavailable";
  }
  return `${lat.toFixed(COORDINATE_DECIMALS)}, ${lng.toFixed(COORDINATE_DECIMALS)}`;
}

/**
 * Format an ISO timestamp as a local date-time string.
 *
 * @param iso - ISO-8601 timestamp.
 * @returns A locale-formatted timestamp.
 */
function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Render the slide-up hit card.
 *
 * @param props - The hit details and dismissal handler.
 * @returns The animated hit card.
 */
export default function HitCard(props: HitCardProps): React.JSX.Element {
  const translateY = useRef(new Animated.Value(240)).current;

  useEffect(() => {
    Animated.timing(translateY, {
      toValue: 0,
      duration: SLIDE_DURATION_MS,
      useNativeDriver: true,
    }).start();
  }, [translateY]);

  const statusColor = STATUS_COLORS[props.status];
  const statusLabel = STATUS_LABELS[props.status];

  return (
    <Animated.View
      testID="hit-card"
      style={[styles.card, { transform: [{ translateY }] }]}
    >
      <View style={styles.header}>
        <Text style={styles.headerText}>HOTLIST HIT</Text>
        <TouchableOpacity
          testID="hit-card-dismiss"
          onPress={props.onDismiss}
          accessibilityLabel="Dismiss hit card"
        >
          <Text style={styles.dismissText}>Swipe to dismiss ✕</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.body}>
        {props.thumbnailUri ? (
          <Image
            testID="hit-card-thumbnail"
            source={{ uri: props.thumbnailUri }}
            style={styles.thumbnail}
          />
        ) : (
          <View style={[styles.thumbnail, styles.thumbnailPlaceholder]} />
        )}

        <View style={styles.details}>
          <Text testID="hit-card-plate" style={styles.plateText}>
            {props.plate}
          </Text>
          <Text style={styles.detailText}>
            Confidence: {props.confidence}%
          </Text>
          <Text testID="hit-card-coordinates" style={styles.detailText}>
            GPS: {formatCoordinates(props.lat, props.lng)}
          </Text>
          <Text style={styles.detailText}>
            {formatTimestamp(props.capturedAt)}
          </Text>
          <View style={[styles.statusPill, { backgroundColor: statusColor }]}>
            <Text testID="hit-card-status" style={styles.statusText}>
              {statusLabel}
            </Text>
          </View>
        </View>
      </View>
    </Animated.View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  card: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "#16213e",
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    borderWidth: 1,
    borderColor: "#e94560",
    paddingBottom: 28,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#e94560",
    borderTopLeftRadius: 15,
    borderTopRightRadius: 15,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  headerText: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "bold",
    letterSpacing: 1,
  },
  dismissText: {
    color: "#fff",
    fontSize: 12,
  },
  body: {
    flexDirection: "row",
    padding: 16,
  },
  thumbnail: {
    width: 96,
    height: 72,
    borderRadius: 8,
    backgroundColor: "#0f3460",
  },
  thumbnailPlaceholder: {
    opacity: 0.4,
  },
  details: {
    flex: 1,
    marginLeft: 16,
  },
  plateText: {
    color: "#fff",
    fontSize: 22,
    fontWeight: "bold",
    letterSpacing: 2,
    fontFamily: "monospace",
  },
  detailText: {
    color: "#c9d1e3",
    fontSize: 12,
    marginTop: 4,
  },
  statusPill: {
    alignSelf: "flex-start",
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginTop: 8,
  },
  statusText: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "600",
  },
});
