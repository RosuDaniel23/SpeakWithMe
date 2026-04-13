import { useEffect, useRef } from "react";
import useEyeTracking from "@/lib/useEyeTracking";
import { speak, useAppDispatch, useAppState } from "./AppContext";

const DISPLAY_ORDER = ["top", "right", "bottom", "left"] as const;

const BACK_WARN_MS = 1000;  // after 1s say "Going back"
const BACK_HOLD_MS = 3000;  // after 3s perform back
const CENTER_CANCEL_MS = 1000; // hold center for 1s to cancel active dwell

export function useGazeOrchestration(): { cameraConnected: boolean } {
  const eye = useEyeTracking();
  const state = useAppState();
  const dispatch = useAppDispatch();
  const centerCancelTimerRef = useRef<number | null>(null);
  const activeOptionIdRef = useRef<string | null>(null);
  activeOptionIdRef.current = state.activeOptionId;

  // Only force-show calibration if backend loses it mid-session (e.g. after reset).
  // CalibrationPage controls its own dismissal via onDone().
  useEffect(() => {
    if (eye.eye_tracking_status === "not_calibrated") {
      dispatch({ type: "SET_SHOW_CALIB", show: true });
    }
  }, [eye.eye_tracking_status, dispatch]);

  // gaze → active option & dwell lifecycle
  useEffect(() => {
    if (state.showCalibration) return;
    if (state.isLocked) return;
    if (eye.eye_tracking_status !== "calibrated") return;

    const zone = eye.hover_zone as string | null;

    // Center zone: start a 1s timer to cancel any active dwell
    if (!zone || zone === "center") {
      if (activeOptionIdRef.current !== null && !centerCancelTimerRef.current) {
        centerCancelTimerRef.current = window.setTimeout(() => {
          dispatch({ type: "SET_ACTIVE", optionId: null });
          dispatch({ type: "STOP_DWELL" });
          dispatch({ type: "RESET_PROGRESS" });
          dispatch({ type: "SET_SELECTION_TRIGGERED", val: false });
          centerCancelTimerRef.current = null;
        }, CENTER_CANCEL_MS);
      }
      return;
    }

    // Moved away from center — clear the cancel timer
    if (centerCancelTimerRef.current) {
      clearTimeout(centerCancelTimerRef.current);
      centerCancelTimerRef.current = null;
    }

    const idx = DISPLAY_ORDER.indexOf(zone as any);
    if (idx === -1 || !state.currentNode.options) return;

    const target = state.currentNode.options[idx];
    if (!target) return;

    if (state.activeOptionId !== target.id) {
      dispatch({ type: "SET_ACTIVE", optionId: target.id });
      dispatch({ type: "RESET_PROGRESS" });
      dispatch({ type: "START_DWELL" });
    } else if (!state.isSelecting) {
      dispatch({ type: "START_DWELL" });
    }

    return () => {
      if (centerCancelTimerRef.current) {
        clearTimeout(centerCancelTimerRef.current);
        centerCancelTimerRef.current = null;
      }
    };
  }, [
    eye.hover_zone,
    eye.eye_tracking_status,
    state.currentNode,
    dispatch,
    state.showCalibration,
    state.isLocked,
  ]);

  // --- NEW effect: eyes-closed → warn at 1s, back at 3s
  const warnTimerRef = useRef<number | null>(null);
  const backTimerRef = useRef<number | null>(null);
  const warnedRef = useRef(false);

  useEffect(() => {
    if (state.showCalibration) return;
    if (state.isLocked) return;
    if (eye.eye_tracking_status !== "calibrated") return;
    if (state.selectedPath.length === 0) return; // at root, no back possible
    const clearTimers = () => {
      if (warnTimerRef.current) {
        clearTimeout(warnTimerRef.current);
        warnTimerRef.current = null;
      }
      if (backTimerRef.current) {
        clearTimeout(backTimerRef.current);
        backTimerRef.current = null;
      }
      warnedRef.current = false;
    };

    if (eye.eyes_closed) {
      // Pause any ongoing dwell/progress while eyes are closed
      dispatch({ type: "STOP_DWELL" });
      dispatch({ type: "RESET_PROGRESS" });

      // schedule 1s voice prompt
      if (!warnTimerRef.current) {
        warnTimerRef.current = window.setTimeout(() => {
          if (!warnedRef.current) {
            speak("back in 2 seconds");
            warnedRef.current = true;
          }
        }, BACK_WARN_MS);
      }

      // schedule 3s actual back action
      if (!backTimerRef.current) {
        backTimerRef.current = window.setTimeout(() => {
          dispatch({ type: "SELECTION_BACK" });
          clearTimers();
        }, BACK_HOLD_MS);
      }
    } else {
      // Eyes opened: cancel any pending back
      if (warnedRef.current) 
        speak("back cancelled");
      clearTimers();
    }

    // cleanup on unmount / dep changes
    return () => {
      if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
      if (backTimerRef.current) clearTimeout(backTimerRef.current);
    };
  }, [
    eye.eyes_closed,
    eye.eye_tracking_status,
    state.selectedPath,
    dispatch,
    state.showCalibration,
    state.isLocked,
  ]);

  return { cameraConnected: eye.camera_connected };
}
