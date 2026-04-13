import { type DecisionTreeNode, DECISION_TREE } from "@/options";
import type { AppAction, AppState } from "./appTypes";

export const initialAppState = (confirmDurationMs = 3000): AppState => ({
  currentNode: DECISION_TREE,
  selectedPath: [],
  activeOptionId: null,
  progress: 0,
  isSelecting: false,
  currentQuestion: DECISION_TREE.label,
  showCalibration: true,
  lastSelectedZone: null,
  confirmDurationMs,
  selectionTriggered: false,
  pendingSummary: null,
  isLocked: false,
  summaryCountdown: null,
});

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SET_NODE":
      return {
        ...state,
        currentNode: action.node,
        currentQuestion: action.node.label,
        selectedPath: [...state.selectedPath, action.node],
      };
    case "SET_ACTIVE":
      return {
        ...state,
        activeOptionId: action.optionId,
        progress: action.optionId ? 0 : 0,
      };
    case "START_DWELL":
      return { ...state, isSelecting: true };
    case "STOP_DWELL":
      return { ...state, isSelecting: false };
    case "RESET_PROGRESS":
      return { ...state, progress: 0 };
    case "TICK_PROGRESS":
      return { ...state, progress: Math.min(100, state.progress + action.deltaPct) };
    case "SET_QUESTION":
      return { ...state, currentQuestion: action.text };
    case "SET_SHOW_CALIB":
      if (!action.show) {
        return {
          ...state,
          showCalibration: false,
          currentNode: DECISION_TREE,
          currentQuestion: DECISION_TREE.question ?? DECISION_TREE.label,
          selectedPath: [],
          activeOptionId: null,
          progress: 0,
          isSelecting: false,
          selectionTriggered: false,
        };
      }
      return { ...state, showCalibration: true };
    case "SET_SELECTION_TRIGGERED":
      return { ...state, selectionTriggered: action.val };
    case "SET_SUMMARY":
      return { ...state, pendingSummary: action.text };
    case "CLEAR_SUMMARY":
      return { ...state, pendingSummary: null };
    case "LOCK_SCREEN":
      return { ...state, isLocked: true };
    case "UNLOCK_SCREEN":
      return { ...state, isLocked: false };
    case "SET_COUNTDOWN":
      return { ...state, summaryCountdown: action.seconds };
    case "SELECTION_BACK":
      const prev_node = state.selectedPath.at(-2) || DECISION_TREE;
      return {
        ...state,
        selectedPath: state.selectedPath.slice(0, -1),
        currentNode: prev_node,
        currentQuestion: prev_node.question ?? prev_node.label,
        showCalibration: false, // don't re-show calibration on back
      };
    case "RESET_TO_ROOT":
      return {
        ...state,
        currentNode: DECISION_TREE,
        currentQuestion: DECISION_TREE.label,
        selectedPath: [],
        activeOptionId: null,
        isSelecting: false,
        progress: 0,
        selectionTriggered: false,
        lastSelectedZone: null,
        pendingSummary: null,
        isLocked: false,
        summaryCountdown: null,
      };
    default:
      return state;
  }
}
