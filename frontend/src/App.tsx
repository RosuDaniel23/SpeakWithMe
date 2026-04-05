import "./App.css";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { iconMap } from "./options";
import TriangleZone from "@/components/TriangleZone";
import type { ResolvedOption } from "@/components/TriangleZone";
import SelectionTerminalBar from "@/components/SelectionTerminalBar";
import CalibrationPage from "@/components/CalibrationPage";

import { AppProvider, useAppDispatch, useAppState, speak } from "@/state/AppContext";
import { useDwellController } from "@/state/useDwellController";
import { useGazeOrchestration } from "@/state/useGazeOrchestration";
import { EmergencyButton } from "@/components/EmergencyButton";
import { SummaryModal } from "@/components/SummaryModal";
import { useEffect } from "react";

function AppInner() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  
  useEffect(() => {
    speak(state.currentQuestion);
  }, [state.currentQuestion]);

  // map id → full option object from current node
  const getActiveOption = (id: string) => state.currentNode.options?.find(o => o.id === id);
  const { cameraConnected } = useGazeOrchestration();
  useDwellController(getActiveOption);

  const handleZoneClick = (option: ResolvedOption) => {
    speak(option.label);
    dispatch({ type: "STOP_DWELL" });
    dispatch({ type: "RESET_PROGRESS" });
    dispatch({ type: "SET_ACTIVE", optionId: option.id });
    dispatch({ type: "START_DWELL" });
  };

  const handleCancelSelection = () => {
    dispatch({ type: "STOP_DWELL" });
    dispatch({ type: "RESET_PROGRESS" });
    dispatch({ type: "SET_ACTIVE", optionId: null });
    dispatch({ type: "SET_SELECTION_TRIGGERED", val: false });
  }

  const handleBack = () => {
    dispatch({ type: "SELECTION_BACK" });
  };

  if (state.showCalibration) {
    return <CalibrationPage onDone={() => dispatch({ type: "SET_SHOW_CALIB", show: false })} />;
  }
  return (
    <div className="min-h-screen bg-background text-foreground overflow-hidden">
      {state.selectedPath.length > 0 && (
        <Button
          onClick={handleBack}
          className="fixed top-6 left-6 z-50 bg-secondary hover:bg-secondary/90 text-secondary-foreground text-lg px-6 py-4"
          size="lg"
          aria-label="Go back to main menu"
        >
          <ArrowLeft className="w-6 h-6 mr-2" /> Back
        </Button>
      )}

      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 text-center max-w-2xl px-8">
        <h1 className="question-heading text-3xl md:text-5xl lg:text-6xl font-bold text-balance mb-4 drop-shadow-lg">
          {state.currentQuestion}
        </h1>
        {/* {state.selectedPath.length > 0 && (
          <p className="text-lg md:text-xl text-white/80 drop-shadow">
            Path: {state.selectedPath.map(n => n.label).join(" → ")}
          </p>
        )} */}
      </div>

      <div className="relative w-full h-screen overflow-hidden">
        {/* Triangular zones */}
        {state.currentNode.options?.map((option, index) => (
          <TriangleZone
            key={option.id}
            option={{ ...option, icon: option.icon ? iconMap[option.icon] : undefined }}
            position={["top", "right", "bottom", "left"][index] as "top" | "right" | "bottom" | "left"}
            onSelect={handleZoneClick}
            onCancel={handleCancelSelection}
            isActive={state.activeOptionId === option.id}
            progress={state.activeOptionId === option.id ? state.progress : 0}
          />
        ))}
      </div>

      <SelectionTerminalBar
        selectedPath={state.selectedPath}
        activeLabel={
          state.activeOptionId && state.currentNode.options
            ? state.currentNode.options.find((o) => o.id === state.activeOptionId)?.label ?? null
            : null
        }
      />
      <EmergencyButton />
      {!cameraConnected && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-500 text-black text-center font-bold py-2 text-lg">
          Camera lost — reconnecting…
        </div>
      )}
      {state.pendingSummary && (
        <SummaryModal
          summary={state.pendingSummary}
          onDismiss={() => {
            dispatch({ type: "CLEAR_SUMMARY" });
            dispatch({ type: "RESET_TO_ROOT" });
          }}
        />
      )}
    </div>
  );
}

export default function MedicalCommunicationApp() {
  return (
    <AppProvider>
      <AppInner />
    </AppProvider>
  );
}
