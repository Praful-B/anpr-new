/**
 * @module Login
 * Login screen for the RAKSHAK mobile app.
 *
 * Accepts email and password, authenticates via POST /auth/login,
 * stores tokens, and navigates to the Scanner screen on success.
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
} from "react-native";
import { apiRequest, ApiError } from "../services/api";
import { setTokens } from "../store/auth";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Button disabled opacity when loading. */
const LOADING_OPACITY = 0.7;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Props for the Login screen. */
interface LoginProps {
  /** Navigation function to switch screens. */
  navigation: { navigate: (screen: string) => void };
}

/** Shape of the login response from the backend. */
interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: {
    id: string;
    name: string;
    role: string;
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Login screen — authenticates citizens, volunteers, and officers.
 *
 * @param props - Navigation props.
 * @returns The login form JSX.
 */
export default function Login({ navigation }: LoginProps): React.JSX.Element {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = useCallback(async () => {
    if (!email.trim() || !password.trim()) {
      Alert.alert("Error", "Please enter both email and password.");
      return;
    }

    setLoading(true);
    try {
      const result = (await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      })) as LoginResponse;

      await setTokens(result.access_token, result.refresh_token);
      navigation.navigate("Scanner");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "An unexpected error occurred.";
      Alert.alert("Login Failed", message);
    } finally {
      setLoading(false);
    }
  }, [email, password, navigation]);

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
      <View style={styles.inner}>
        <Text style={styles.title}>RAKSHAK</Text>
        <Text style={styles.subtitle}>Privacy-First ANPR Network</Text>

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
          placeholder="Password"
          placeholderTextColor="#888"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="password"
        />

        <TouchableOpacity
          style={[styles.button, loading && { opacity: LOADING_OPACITY }]}
          onPress={handleLogin}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Login</Text>
          )}
        </TouchableOpacity>

        <TouchableOpacity onPress={() => navigation.navigate("Register")}>
          <Text style={styles.linkText}>Don't have an account? Register</Text>
        </TouchableOpacity>
      </View>
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
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 32,
  },
  title: {
    fontSize: 36,
    fontWeight: "bold",
    color: "#e94560",
    textAlign: "center",
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    color: "#aaa",
    textAlign: "center",
    marginBottom: 40,
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
