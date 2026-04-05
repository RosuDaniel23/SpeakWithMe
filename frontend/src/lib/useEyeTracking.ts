import { useEffect, useRef, useState } from 'react';

export interface EyeTrackingState {
  eye_tracking_status: 'calibrated' | 'not_calibrated';
  hover_zone: 'top' | 'bottom' | 'left' | 'right' | null;
  selected_zone: 'top' | 'bottom' | 'left' | 'right' | null;
  last_activation_ts: number | null;
  eyes_closed: boolean | null;
  camera_connected: boolean;
}

const INITIAL: EyeTrackingState = {
  eye_tracking_status: 'not_calibrated',
  hover_zone: null,
  selected_zone: null,
  last_activation_ts: null,
  eyes_closed: false,
  camera_connected: true,
};

export interface UseEyeTrackingOptions {
  url?: string;                 // e.g. ws://localhost:8000/ws/eye_tracking
  reconnectMs?: number;         // default 1000
  selectedDebounceMs?: number;  // default 150
  onUpdate?: (s: EyeTrackingState) => void; // called with the *displayed* state
}

export function useEyeTracking(opts: UseEyeTrackingOptions = {}) {
  const {
    url = 'ws://localhost:8000/ws/eye_tracking',
    reconnectMs = 1000,
    selectedDebounceMs = 150,
    onUpdate,
  } = opts;

  const [state, setState] = useState<EyeTrackingState>(INITIAL);

  // Keep a ref to the latest displayed state for comparisons & timers
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
    onUpdate?.(state); // notify only when displayed state changes
  }, [state, onUpdate]);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);

  // Debounce machinery for hover_zone
  const pendingHoverRef = useRef<EyeTrackingState['hover_zone'] | null>(null);
  const hoverTimerRef = useRef<number | null>(null);

  // Helper to clear pending hover timer
  const clearHoverTimer = () => {
    if (hoverTimerRef.current) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    pendingHoverRef.current = null;
  };

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          // optionally ping
        };

        ws.onmessage = (ev) => {
          try {
            const incoming: EyeTrackingState = JSON.parse(ev.data);

            // 1) Update everything EXCEPT hover_zone immediately (to avoid UI stutter)
            setState((prev) => ({
              ...incoming,
              hover_zone: prev.hover_zone // keep displayed hover for now
            }));

            // 2) Debounce hover_zone changes
            const displayed = stateRef.current.hover_zone;
            const nextHover = incoming.hover_zone;

            if (nextHover === displayed) {
              // Change reverted to the displayed value -> cancel any pending switch
              clearHoverTimer();
              return;
            }

            // If we get a new candidate different from current pending, restart the timer
            if (pendingHoverRef.current !== nextHover) {
              clearHoverTimer();
              pendingHoverRef.current = nextHover;

              hoverTimerRef.current = window.setTimeout(() => {
                // Commit the pending hover after debounce window
                const commitTo = pendingHoverRef.current;
                clearHoverTimer();
                setState((curr) => ({
                  ...curr,
                  hover_zone: commitTo ?? curr.hover_zone,
                }));
              }, selectedDebounceMs);
            }
          } catch {
            /* ignore parse errors */
          }
        };

        ws.onclose = () => {
          wsRef.current = null;
          clearHoverTimer();
          scheduleReconnect();
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch {
        scheduleReconnect();
      }
    }

    function scheduleReconnect() {
      if (cancelled) return;
      if (reconnectRef.current) window.clearTimeout(reconnectRef.current);
      reconnectRef.current = window.setTimeout(connect, reconnectMs);
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectRef.current) window.clearTimeout(reconnectRef.current);
      clearHoverTimer();
      wsRef.current?.close();
    };
  }, [url, reconnectMs, selectedDebounceMs]);

  return state;
}

export default useEyeTracking;
