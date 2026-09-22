/**
 * @module CitizenComplaint
 * Complaint filing screen for citizens.
 *
 * Collects a licence plate number and optional proof reference, then
 * POSTs to POST /complaints. Rate limited to 3 complaints per user per
 * 24 hours on the backend.
 */

import React, { useState, useCallback } from "react";
import {
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from "react-native";
import { apiRequest, ApiError } from "../services/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Indian licence plate pattern hint for input validation. */
const PLATE_HINT = "e.g. MH12AB1234";

/** Button disabled opacity when loading. */
const LOADING_OPACITY = 0.7;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Props for the CitizenComplaint screen. */
interface CitizenComplaintProps {
  /** Navigation function to switch screens. */
  navigation: { navigate: (screen: string) => void };
}

/** Shape of the complaint creation response. */
interface ComplaintResponse {
  id: string;
  plate: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Citizen complaint screen — file a stolen vehicle complaint.
 *
 * @param props - Navigation props.
 * @returns The complaint form JSX.
 */
export default function CitizenComplaint({
  navigation,
}: CitizenComplaintProps): React.JSX.Element {
  const [plate, setPlate] = useState("");
  const [proofRef, setProofRef] = useState("");
  const [loading, setLoading] = useState(false);

  const normaliseInput = useCallback((raw: string): string => {
    return raw.toUpperCase().replace(/[\s\-]/g, "");
  }, []);

  const handleSubmit = useCallback(async () => {
    const normalisedPlate = normaliseInput(plate);

    if (!normalisedPlate.trim()) {
      Alert.alert("Error", "Please enter the vehicle licence plate number.");
      return;
    }

    setLoading(true);
    try {
      const result = (await apiRequest("/complaints", {
        method: "POST",
        body: JSON.stringify({
          plate: normalisedPlate,
          proof_ref: proofRef.trim() || undefined,
        }),
      })) as ComplaintResponse;

      Alert.alert(
        "Complaint Filed",
        `Plate: ${result.plate}\nStatus: ${result.status}`,
        [{ text: "OK", onPress: () => navigation.navigate("Scanner") }]
      );
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "An unexpected error occurred.";
      Alert.alert("Filing Failed", message);
    } finally {
      setLoading(false);
    }
  }, [plate, proofRef, normaliseInput, navigation]);

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
      <ScrollView contentContainerStyle={styles.inner}>
        <Text style={styles.title}>File a Complaint</Text>
        <Text style={styles.description}>
          Report a stolen vehicle. After ownership verification by police, the
          plate will be added to the active hotlist for scanning.
        </Text>

        <Text style={styles.label}>Licence Plate Number *</Text>
        <TextInput
          style={styles.input}
          placeholder={PLATE_HINT}
          placeholderTextColor="#666"
          value={plate}
          onChangeText={(text) => setPlate(normaliseInput(text))}
          autoCapitalize="characters"
          maxLength={20}
        />

        <Text style={styles.label}>Proof Reference (optional)</Text>
        <TextInput
          style={styles.input}
          placeholder="FIR number, document link, etc."
          placeholderTextColor="#666"
          value={proofRef}
          onChangeText={setProofRef}
          autoCapitalize="none"
        />

        <TouchableOpacity
          style={[styles.button, loading && { opacity: LOADING_OPACITY }]}
          onPress={handleSubmit}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Submit Complaint</Text>
          )}
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
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
  inner: {
    flexGrow: 1,
    justifyContent: "center",
    paddingHorizontal: 32,
    paddingVertical: 40,
  },
  title: {
    fontSize: 28,
    fontWeight: "bold",
    color: "#fff",
    textAlign: "center",
    marginBottom: 12,
  },
  description: {
    fontSize: 14,
    color: "#aaa",
    textAlign: "center",
    marginBottom: 32,
    lineHeight: 20,
  },
  label: {
    color: "#aaa",
    fontSize: 14,
    marginBottom: 8,
  },
  input: {
    backgroundColor: "#16213e",
    color: "#fff",
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#0f3460",
  },
  button: {
    backgroundColor: "#e94560",
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
});
