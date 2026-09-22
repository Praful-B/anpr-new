/**
 * @module App
 * Root component for the RAKSHAK mobile app.
 *
 * Manages navigation between Login, Register, CitizenComplaint,
 * Scanner, and History screens. Restores auth tokens on startup
 * and initialises hotlist sync.
 */

import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { StatusBar } from "expo-status-bar";

import {
  restoreTokens,
  isAuthenticated,
  onAuthChange,
} from "./src/store/auth";
import { startAutoSync, stopAutoSync } from "./src/services/hotlist";
import { initInference } from "./src/ai/inference";

import Login from "./src/screens/Login";
import Register from "./src/screens/Register";
import CitizenComplaint from "./src/screens/CitizenComplaint";
import Scanner from "./src/screens/Scanner";
import History from "./src/screens/History";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Available screen names. */
type ScreenName = "Login" | "Register" | "CitizenComplaint" | "Scanner" | "History";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Root component — manages auth state and screen routing.
 *
 * @returns The active screen or a loading indicator.
 */
export default function App(): React.JSX.Element {
  const [currentScreen, setCurrentScreen] = useState<ScreenName>("Login");
  const [initializing, setInitializing] = useState(true);

  // Navigate to Scanner if authenticated, otherwise Login.
  const handleAuthChange = useCallback(() => {
    if (isAuthenticated()) {
      startAutoSync();
      setCurrentScreen("Scanner");
    } else {
      stopAutoSync();
      setCurrentScreen("Login");
    }
  }, []);

  // Initialise on mount.
  useEffect(() => {
    const init = async () => {
      await initInference();
      const restored = await restoreTokens();
      if (restored) {
        startAutoSync();
        setCurrentScreen("Scanner");
      }
      setInitializing(false);
    };

    init();

    const unsubscribe = onAuthChange(handleAuthChange);
    return () => {
      unsubscribe();
      stopAutoSync();
    };
  }, [handleAuthChange]);

  // Navigation helper passed to screens.
  const navigation = {
    navigate: (screen: string) => setCurrentScreen(screen as ScreenName),
    goBack: () => setCurrentScreen("Login"),
  };

  if (initializing) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color="#e94560" />
        <Text style={styles.loadingText}>Loading RAKSHAK...</Text>
        <StatusBar style="light" />
      </View>
    );
  }

  const renderScreen = (): React.JSX.Element => {
    switch (currentScreen) {
      case "Register":
        return <Register navigation={navigation} />;
      case "CitizenComplaint":
        return <CitizenComplaint navigation={navigation} />;
      case "Scanner":
        return <Scanner navigation={navigation} />;
      case "History":
        return <History navigation={navigation} />;
      case "Login":
      default:
        return <Login navigation={navigation} />;
    }
  };

  return (
    <View style={styles.container}>
      {renderScreen()}
      <StatusBar style="light" />
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
  loadingText: {
    color: "#aaa",
    fontSize: 14,
    marginTop: 16,
  },
});
