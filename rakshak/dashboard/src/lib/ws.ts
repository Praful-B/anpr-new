/**
 * @module ws
 * WebSocket client for the RAKSHAK dashboard real-time channel.
 *
 * Connects to /ws/dashboard with a JWT token query parameter,
 * automatically reconnects on disconnect with exponential backoff,
 * and dispatches incoming events to registered subscriber callbacks.
 */

import { getAccessToken } from "./auth";
import { WS_BASE_URL } from "./apiBase";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Initial delay before the first reconnect attempt (ms). */
const INITIAL_RETRY_DELAY_MS = 1000;

/** Maximum delay between reconnect attempts (ms). */
const MAX_RETRY_DELAY_MS = 30000;

/** Multiplier applied to the retry delay after each failed attempt. */
const BACKOFF_MULTIPLIER = 2;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Supported WebSocket event types dispatched to subscribers. */
export type WsEventType = "new_sighting" | "hotlist_change" | "connected" | "ping";

/** Shape of a WebSocket message received from the server. */
export interface WsMessage {
  readonly type: WsEventType;
  readonly data?: Record<string, unknown>;
  readonly message?: string;
}

/** Callback signature for WebSocket event subscribers. */
export type WsSubscriber = (message: WsMessage) => void;

/** Connection state of the WebSocket client. */
export type WsConnectionState = "connecting" | "open" | "closed";

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

/**
 * A singleton WebSocket client that manages a persistent connection
 * to the dashboard real-time channel with automatic reconnection.
 */
class DashboardWsClient {
  private _socket: WebSocket | null = null;
  private _subscribers: Set<WsSubscriber> = new Set();
  private _retryDelay: number = INITIAL_RETRY_DELAY_MS;
  private _retryTimer: ReturnType<typeof setTimeout> | null = null;
  private _intentionalClose: boolean = false;
  private _state: WsConnectionState = "closed";
  private _stateListeners: Set<(state: WsConnectionState) => void> = new Set();

  /** Current connection state. */
  get state(): WsConnectionState {
    return this._state;
  }

  /**
   * Open a WebSocket connection to the dashboard channel.
   *
   * Uses the current in-memory access token for authentication.
   * If already connected, this is a no-op.
   */
  connect(): void {
    if (this._socket && this._socket.readyState === WebSocket.OPEN) {
      return;
    }

    const token = getAccessToken();
    if (!token) {
      return;
    }

    this._intentionalClose = false;
    this._setState("connecting");

    const url = `${WS_BASE_URL}?token=${encodeURIComponent(token)}`;
    this._socket = new WebSocket(url);

    this._socket.onopen = (): void => {
      this._retryDelay = INITIAL_RETRY_DELAY_MS;
      this._setState("open");
    };

    this._socket.onmessage = (event: MessageEvent): void => {
      try {
        const message: WsMessage = JSON.parse(event.data as string) as WsMessage;
        if (message.type === "ping") {
          return;
        }
        this._notifySubscribers(message);
      } catch {
        // Malformed message — ignore.
      }
    };

    this._socket.onclose = (): void => {
      this._setState("closed");
      if (!this._intentionalClose) {
        this._scheduleReconnect();
      }
    };

    this._socket.onerror = (): void => {
      this._socket?.close();
    };
  }

  /**
   * Gracefully close the WebSocket connection.
   * Prevents automatic reconnection.
   */
  disconnect(): void {
    this._intentionalClose = true;
    if (this._retryTimer !== null) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
    if (this._socket) {
      this._socket.close();
      this._socket = null;
    }
    this._setState("closed");
  }

  /**
   * Register a callback to receive WebSocket events.
   *
   * @param subscriber - Function invoked for each non-ping event.
   * @returns Unsubscribe function.
   */
  subscribe(subscriber: WsSubscriber): () => void {
    this._subscribers.add(subscriber);
    return () => {
      this._subscribers.delete(subscriber);
    };
  }

  /**
   * Register a callback for connection state changes.
   *
   * @param listener - Function invoked when the connection state changes.
   * @returns Unsubscribe function.
   */
  onStateChange(listener: (state: WsConnectionState) => void): () => void {
    this._stateListeners.add(listener);
    return () => {
      this._stateListeners.delete(listener);
    };
  }

  /** Notify all registered subscribers of an incoming message. */
  private _notifySubscribers(message: WsMessage): void {
    for (const subscriber of this._subscribers) {
      subscriber(message);
    }
  }

  /** Update internal state and notify state listeners. */
  private _setState(state: WsConnectionState): void {
    this._state = state;
    for (const listener of this._stateListeners) {
      listener(state);
    }
  }

  /** Schedule a reconnect attempt with exponential backoff. */
  private _scheduleReconnect(): void {
    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      this.connect();
    }, this._retryDelay);
    this._retryDelay = Math.min(
      this._retryDelay * BACKOFF_MULTIPLIER,
      MAX_RETRY_DELAY_MS,
    );
  }
}

// ---------------------------------------------------------------------------
// Singleton export
// ---------------------------------------------------------------------------

/** Singleton WebSocket client instance for the dashboard. */
export const wsClient = new DashboardWsClient();
