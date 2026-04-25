import { useEffect, useRef } from "react";
import { useAppDispatch, useAppState, commitSelection, useSessionCallbacks } from "./AppContext";

export function useDwellController(getActiveOption: (id: string) => any) {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const callbacks = useSessionCallbacks();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectionTriggeredRef = useRef(state.selectionTriggered);
  selectionTriggeredRef.current = state.selectionTriggered;

  useEffect(() => {
    if (state.showCalibration || state.isLocked) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      intervalRef.current = null;
      return;
    }
    if (state.activeOptionId && state.isSelecting) {
      const TICK_MS = 30;
      const inc = (100 * TICK_MS) / state.confirmDurationMs;

      dispatch({ type: "SET_SELECTION_TRIGGERED", val: false });

      intervalRef.current = setInterval(() => {
        // bail if already committed — read from ref to avoid stale closure
        if (selectionTriggeredRef.current) return;
        dispatch({ type: "TICK_PROGRESS", deltaPct: inc });
      }, TICK_MS);
    } else {
      if (!state.activeOptionId) dispatch({ type: "RESET_PROGRESS" });
      dispatch({ type: "SET_SELECTION_TRIGGERED", val: false });
      if (intervalRef.current) clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [state.activeOptionId, state.isSelecting, state.confirmDurationMs, state.showCalibration, state.isLocked]);

  // Commit when progress hits 100
  useEffect(() => {
    if (state.showCalibration || state.isLocked) return;
    if (state.progress >= 100 && state.activeOptionId && !state.selectionTriggered) {
      dispatch({ type: "SET_SELECTION_TRIGGERED", val: true });
      dispatch({ type: "STOP_DWELL" });

      // resolve option from id and commit
      
      // TODO: add TTO by chat gpt here or in commitSelection
      // create path from state.selectedPath + current option label or something like that

      // request to backend to get TTO prediction for this path

      const opt = getActiveOption(state.activeOptionId);
      if (opt) commitSelection(state, dispatch, opt, callbacks);
 
      dispatch({ type: "RESET_PROGRESS" });
      dispatch({ type: "SET_ACTIVE", optionId: null });
    }
  }, [state.progress, state.activeOptionId, state.selectionTriggered, dispatch, state]);
}
