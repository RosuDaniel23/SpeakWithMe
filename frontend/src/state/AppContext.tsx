import { createContext, useContext, useMemo, useReducer } from "react";
import { appReducer, initialAppState } from "./appReducer";
import type { AppAction, AppState } from "./appTypes";
import { type DecisionTreeNode } from "@/options";
import { api } from "@/lib/api";

type Dispatch = (a: AppAction) => void;

const AppStateCtx = createContext<AppState | null>(null);
const AppDispatchCtx = createContext<Dispatch | null>(null);

// Simple speech helper (kept near state to be reusable)
export const speak = (text: string) => {
  if (typeof window === "undefined") return;
  const synth = (window as any).speechSynthesis as SpeechSynthesis | undefined;
  if (!synth) return;
  if (synth.speaking) synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1;
  u.pitch = 1;
  synth.speak(u);
};

// Promise-based speech: resolves when TTS finishes (or immediately if unavailable)
const speakPromise = (text: string): Promise<void> =>
  new Promise((resolve) => {
    if (typeof window === "undefined") { resolve(); return; }
    const synth = (window as any).speechSynthesis as SpeechSynthesis | undefined;
    if (!synth) { resolve(); return; }
    if (synth.speaking) synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.pitch = 1;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    synth.speak(u);
  });


export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, undefined, () => initialAppState(3000));

  const value = useMemo(() => state, [state]);

  return (
    <AppStateCtx.Provider value={value}>
      <AppDispatchCtx.Provider value={dispatch}>{children}</AppDispatchCtx.Provider>
    </AppStateCtx.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppStateCtx);
  if (!ctx) throw new Error("useAppState must be used within AppProvider");
  return ctx;
}
export function useAppDispatch() {
  const ctx = useContext(AppDispatchCtx);
  if (!ctx) throw new Error("useAppDispatch must be used within AppProvider");
  return ctx;
}

/** Selection orchestration helper you can call from components */
export function commitSelection(
  state: AppState,
  dispatch: Dispatch,
  option: DecisionTreeNode
) {
  // capture last zone by index → label
  const displayOrder = ["top", "right", "bottom", "left"] as const;
  const zoneIndex = state.currentNode.options
    ? state.currentNode.options.findIndex((o) => o.id === option.id)
    : -1;
  const zoneLabel = displayOrder[zoneIndex] ?? null;

  if (option.options) {
    // go deeper in tree
    dispatch({ type: "SET_NODE", node: option });
    dispatch({ type: "SET_QUESTION", text: option.question ?? option.label });
    return;
  }

  // leaf selection
  const fullNodes = [...state.selectedPath, option];
  const path = fullNodes.map(node => node.label);

  dispatch({ type: "SET_QUESTION", text: "Generating summary…" });

  api("/get_llm_summary", {
    method: "POST",
    body: JSON.stringify({ labels: path }),
  })
  .then(data => {
    const summary = data.summary || "Patient reports: " + fullNodes.map(n => n.label).join(" → ");
    dispatch({ type: "LOCK_SCREEN" });
    dispatch({ type: "SET_SUMMARY", text: summary });
    // Persist to backend (fire-and-forget)
    api("/sessions", {
      method: "POST",
      body: JSON.stringify({ path, summary }),
    }).catch(() => {});
    // Speak summary, then start 10s countdown before auto-reset
    speakPromise(summary).then(() => {
      let countdown = 10;
      dispatch({ type: "SET_COUNTDOWN", seconds: countdown });
      const timer = setInterval(() => {
        countdown--;
        if (countdown <= 0) {
          clearInterval(timer);
          dispatch({ type: "SET_COUNTDOWN", seconds: null });
          dispatch({ type: "UNLOCK_SCREEN" });
          dispatch({ type: "RESET_TO_ROOT" });
        } else {
          dispatch({ type: "SET_COUNTDOWN", seconds: countdown });
        }
      }, 1000);
    });
  })
  .catch(() => {
    dispatch({ type: "SET_QUESTION", text: "Could not generate summary. Please try again." });
  });
}
