import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";

export function EmergencyButton() {
  const [active, setActive] = useState(false);

  const trigger = useCallback(async () => {
    setActive(true);
    try {
      await api("/emergency", { method: "POST" });
    } catch {
      // Even if backend call fails, show the alert
    }
    // Play alarm via Web Audio API
    try {
      const ctx = new AudioContext();
      for (let i = 0; i < 3; i++) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = "square";
        osc.frequency.value = 880;
        gain.gain.value = 0.6;
        osc.start(ctx.currentTime + i * 0.4);
        osc.stop(ctx.currentTime + i * 0.4 + 0.35);
      }
    } catch {
      // Audio context unavailable — visual alert is still shown
    }
  }, []);

  // Keyboard shortcut: Escape twice within 1s
  useEffect(() => {
    let firstEsc = 0;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        const now = Date.now();
        if (now - firstEsc < 1000) {
          trigger();
        } else {
          firstEsc = now;
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [trigger]);

  return (
    <>
      {/* Always-visible emergency button */}
      <button
        onClick={trigger}
        className="fixed bottom-6 right-6 z-50 bg-red-600 hover:bg-red-700 active:bg-red-800 text-white font-bold text-lg px-6 py-4 rounded-2xl shadow-2xl ring-4 ring-red-400/50 transition-all"
        aria-label="Emergency — call for help"
      >
        🚨 EMERGENCY
      </button>

      {/* Fullscreen overlay when triggered */}
      {active && (
        <div
          className="fixed inset-0 z-[100] bg-red-600 flex flex-col items-center justify-center cursor-pointer"
          onClick={() => setActive(false)}
          role="alertdialog"
          aria-live="assertive"
          aria-label="Emergency alert active"
        >
          <div className="text-white text-center select-none">
            <div className="text-8xl mb-6">🚨</div>
            <h1 className="text-5xl md:text-7xl font-extrabold mb-4 tracking-wide">
              EMERGENCY
            </h1>
            <p className="text-2xl md:text-3xl font-semibold opacity-90">
              HELP REQUESTED
            </p>
            <p className="mt-10 text-lg opacity-70">
              Tap anywhere to dismiss
            </p>
          </div>
        </div>
      )}
    </>
  );
}
