/**
 * @module History
 * Complaint history screen for citizens.
 *
 * Displays the user's filed complaints via GET /complaints/mine with
 * status indicators and timestamps.
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  View,
  Text,
  FlatList,
  Image,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  TouchableOpacity,
} from "react-native";
import { apiRequest, ApiError } from "../services/api";
import { listRecentHits, type RecentHit } from "../services/hitHistory";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Status color mapping for complaints. */
const STATUS_COLORS: Record<string, string> = {
  PENDING_VERIFICATION: "#f0ad4e",
  VERIFIED: "#5cb85c",
  REJECTED: "#d9534f",
};

/** Delivery-status color mapping for recent hits. */
const HIT_STATUS_COLORS: Record<string, string> = {
  sending: "#f0ad4e",
  sent: "#5cb85c",
  throttled: "#f0ad4e",
  rejected: "#d9534f",
  queued: "#5bc0de",
};

/** Delivery-status labels for recent hits. */
const HIT_STATUS_LABELS: Record<string, string> = {
  sending: "Sending...",
  sent: "Sent ✓",
  throttled: "Throttled",
  rejected: "Rejected",
  queued: "Queued (offline)",
};

/** Which list the History screen is showing. */
type HistoryTab = "hits" | "complaints";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of a complaint record from the API. */
interface Complaint {
  id: string;
  plate: string;
  status: string;
  rejection_reason: string | null;
  created_at: string;
}

/** Navigation callbacks injected by the root App component. */
interface HistoryProps {
  /** Navigation callbacks for the tab bar. */
  navigation: {
    /** Switch to another screen by name. */
    navigate: (screen: string) => void;
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * History screen — recent hotlist hits and the user's filed complaints.
 *
 * @param props - Navigation callbacks.
 * @returns The history screen JSX.
 */
export default function History(props: HistoryProps): React.JSX.Element {
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [hits, setHits] = useState<RecentHit[]>([]);
  const [activeTab, setActiveTab] = useState<HistoryTab>("hits");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchComplaints = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const result = (await apiRequest("/complaints/mine")) as Complaint[];
      setComplaints(result);
      setHits(await listRecentHits());
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to load complaints.";
      setError(message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchComplaints();
  }, [fetchComplaints]);

  const renderHit = useCallback(
    ({ item }: { item: RecentHit }) => {
      const statusColor = HIT_STATUS_COLORS[item.status] ?? "#888";
      const statusLabel = HIT_STATUS_LABELS[item.status] ?? item.status;
      const coordinates =
        item.lat !== null && item.lng !== null
          ? `${item.lat.toFixed(4)}, ${item.lng.toFixed(4)}`
          : "Location unavailable";

      return (
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <Text style={styles.plateText}>{item.plate}</Text>
            <View style={[styles.statusBadge, { backgroundColor: statusColor }]}>
              <Text style={styles.statusText}>{statusLabel}</Text>
            </View>
          </View>
          <View style={styles.hitBody}>
            {item.thumbnail_uri ? (
              <Image source={{ uri: item.thumbnail_uri }} style={styles.thumb} />
            ) : null}
            <View style={styles.hitDetails}>
              <Text style={styles.dateText}>{coordinates}</Text>
              <Text style={styles.dateText}>
                Confidence: {item.confidence}%
              </Text>
              <Text style={styles.dateText}>
                {new Date(item.captured_at).toLocaleString("en-IN")}
              </Text>
            </View>
          </View>
        </View>
      );
    },
    []
  );

  const renderComplaint = useCallback(
    ({ item }: { item: Complaint }) => {
      const statusColor = STATUS_COLORS[item.status] ?? "#888";
      const date = new Date(item.created_at).toLocaleDateString("en-IN", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });

      return (
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <Text style={styles.plateText}>{item.plate}</Text>
            <View style={[styles.statusBadge, { backgroundColor: statusColor }]}>
              <Text style={styles.statusText}>
                {item.status.replace(/_/g, " ")}
              </Text>
            </View>
          </View>
          <Text style={styles.dateText}>{date}</Text>
          {item.rejection_reason ? (
            <Text style={styles.rejectionText}>
              Reason: {item.rejection_reason}
            </Text>
          ) : null}
        </View>
      );
    },
    []
  );

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color="#e94560" />
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>{error}</Text>
      </View>
    );
  }

  const showingHits = activeTab === "hits";

  return (
    <View style={styles.container}>
      <Text style={styles.title}>
        {showingHits ? "Recent Hits" : "My Complaints"}
      </Text>

      <View style={styles.tabBar}>
        <TouchableOpacity onPress={() => setActiveTab("hits")}>
          <Text style={[styles.tabText, showingHits && styles.tabTextActive]}>
            Recent Hits ({hits.length})
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setActiveTab("complaints")}>
          <Text style={[styles.tabText, !showingHits && styles.tabTextActive]}>
            Complaints ({complaints.length})
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => props.navigation.navigate("Scanner")}>
          <Text style={styles.tabText}>Back to Scanner</Text>
        </TouchableOpacity>
      </View>

      {showingHits ? (
        <FlatList
          data={hits}
          keyExtractor={(item) => String(item.id)}
          renderItem={renderHit}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => fetchComplaints(true)}
              tintColor="#e94560"
            />
          }
          ListEmptyComponent={
            <Text style={styles.emptyText}>No hotlist hits recorded yet.</Text>
          }
        />
      ) : (
        <FlatList
          data={complaints}
          keyExtractor={(item) => item.id}
          renderItem={renderComplaint}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => fetchComplaints(true)}
              tintColor="#e94560"
            />
          }
          ListEmptyComponent={
            <Text style={styles.emptyText}>No complaints filed yet.</Text>
          }
        />
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#1a1a2e",
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#1a1a2e",
  },
  title: {
    fontSize: 24,
    fontWeight: "bold",
    color: "#fff",
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 8,
  },
  list: {
    paddingHorizontal: 16,
    paddingBottom: 32,
  },
  tabBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 12,
  },
  tabText: {
    color: "#8fb8ff",
    fontSize: 13,
    fontWeight: "600",
  },
  tabTextActive: {
    color: "#fff",
    textDecorationLine: "underline",
  },
  hitBody: {
    flexDirection: "row",
    marginTop: 8,
  },
  hitDetails: {
    flex: 1,
    marginLeft: 12,
  },
  thumb: {
    width: 72,
    height: 54,
    borderRadius: 6,
    backgroundColor: "#0f3460",
  },
  card: {
    backgroundColor: "#16213e",
    borderRadius: 8,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#0f3460",
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  plateText: {
    fontSize: 18,
    fontWeight: "bold",
    color: "#fff",
    letterSpacing: 1,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  statusText: {
    fontSize: 11,
    fontWeight: "600",
    color: "#fff",
    textTransform: "uppercase",
  },
  dateText: {
    fontSize: 12,
    color: "#888",
  },
  rejectionText: {
    fontSize: 12,
    color: "#d9534f",
    marginTop: 8,
  },
  errorText: {
    color: "#d9534f",
    fontSize: 16,
  },
  emptyText: {
    color: "#666",
    textAlign: "center",
    marginTop: 40,
    fontSize: 16,
  },
});
