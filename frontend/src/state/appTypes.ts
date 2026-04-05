import { type DecisionTreeNode } from "../options";

export type EyeStatus = "idle" | "calibrating" | "calibrated";

export interface AppState {
  currentNode: DecisionTreeNode;
  selectedPath: DecisionTreeNode[];
  activeOptionId: string | null;
  progress: number;           // 0..100
  isSelecting: boolean;       // dwell in progress
  currentQuestion: string;
  showCalibration: boolean;
  lastSelectedZone: "top" | "right" | "bottom" | "left" | null;
  confirmDurationMs: number;  // configurable dwell
  selectionTriggered: boolean; // guards double-commit
  pendingSummary: string | null; // LLM summary waiting to be dismissed
}

export type AppAction =
  | { type: "SET_NODE"; node: DecisionTreeNode }
  | { type: "SET_ACTIVE"; optionId: string | null }
  | { type: "START_DWELL" }
  | { type: "STOP_DWELL" }
  | { type: "RESET_PROGRESS" }
  | { type: "TICK_PROGRESS"; deltaPct: number }
  | { type: "SELECTION_BACK" }
  | { type: "SET_QUESTION"; text: string }
  | { type: "SET_SHOW_CALIB"; show: boolean }
  | { type: "SET_SELECTION_TRIGGERED"; val: boolean }
  | { type: "SET_SUMMARY"; text: string }
  | { type: "CLEAR_SUMMARY" }
  | { type: "RESET_TO_ROOT" };
