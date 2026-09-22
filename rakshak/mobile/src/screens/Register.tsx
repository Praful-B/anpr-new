/**
 * @module Register
 * Registration screen for the RAKSHAK mobile app.
 *
 * Collects name, email, phone, password, and role, then POSTs to
 * POST /auth/register. On success, navigates back to Login.
 */

import React, { useState, useCallback } from "react";
import {
  View,
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

/** Available roles for registration. */
const ROLES = ["CITIZEN", "VOLUNTEER"] as const;

/** Button disabled opacity when loading. */
const LOADING_OPACITY = 0.7;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Props for the Register screen. */
interface RegisterProps {
  /** Navigation function to switch screens. */
  navigation: { navigate: (screen: string) => void; goBack: () => void };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Registration screen — creates a new citizen or volunteer account.
 *
 * @param props - Navigation props.
 * @returns The registration form JSX.
 */
export default function Register({
  navigation,
}: RegisterProps): React.JSX.Element {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"CITIZEN" | "VOLUNTEER">("CITIZEN");
  const [loading, setLoading] = useState(false);

  const handleRegister = useCallback(async () => {
    if (!name.trim() || !email.trim() || !password.trim()) {
      Alert.alert("Error", "Name, email, and password are required.");
      return;
    }

    setLoading(true);
    try {
      await apiRequest("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          phone: phone.trim() || undefined,
          password,
          role,
        }),
      });

      Alert.alert("Success", "Account created. Please log in.", [
        { text: "OK", onPress: () => navigation.navigate("Login") },
      ]);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "An unexpected error occurred.";
      Alert.alert("Registration Failed", message);
    } finally {
      setLoading(false);
    }
  }, [name, email, phone, password, role, navigation]);

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
      <ScrollView contentContainerStyle={styles.inner}>
        <Text style={styles.title}>Create Account</Text>

        <TextInput
          style={styles.input}
          placeholder="Full Name"
          placeholderTextColor="#888"
          value={name}
          onChangeText={setName}
          autoCapitalize="words"
        />

        <TextInput
          style={styles.input}
          placeholder="Email"
          placeholderTextColor="#888"
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
        />

        <TextInput
          style={styles.input}
          placeholder="Phone (optional)"
          placeholderTextColor="#888"
          value={phone}
          onChangeText={setPhone}
          keyboardType="phone-pad"
        />

        <TextInput
          style={styles.input}
          placeholder="Password"
          placeholderTextColor="#888"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="new-password"
        />

        <Text style={styles.label}>Role</Text>
        <View style={styles.roleRow}>
          {ROLES.map((r) => (
            <TouchableOpacity
              key={r}
              style={[
                styles.roleButton,
                role === r && styles.roleButtonActive,
              ]}
              onPress={() => setRole(r)}
            >
              <Text
                style={[
                  styles.roleButtonText,
                  role === r && styles.roleButtonTextActive,
                ]}
              >
                {r.charAt(0) + r.slice(1).toLowerCase()}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <TouchableOpacity
          style={[styles.button, loading && { opacity: LOADING_OPACITY }]}
          onPress={handleRegister}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Register</Text>
          )}
        </TouchableOpacity>

        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={styles.linkText}>Already have an account? Login</Text>
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
    marginBottom: 32,
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
  label: {
    color: "#aaa",
    fontSize: 14,
    marginBottom: 8,
  },
  roleRow: {
    flexDirection: "row",
    marginBottom: 24,
    gap: 12,
  },
  roleButton: {
    flex: 1,
    backgroundColor: "#16213e",
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#0f3460",
  },
  roleButtonActive: {
    backgroundColor: "#0f3460",
    borderColor: "#e94560",
  },
  roleButtonText: {
    color: "#aaa",
    fontSize: 14,
  },
  roleButtonTextActive: {
    color: "#fff",
    fontWeight: "600",
  },
  button: {
    backgroundColor: "#e94560",
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
    marginBottom: 16,
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  linkText: {
    color: "#53a8b6",
    textAlign: "center",
    fontSize: 14,
  },
});
