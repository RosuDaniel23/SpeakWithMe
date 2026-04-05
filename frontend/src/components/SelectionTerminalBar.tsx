import type { DecisionTreeNode } from '@/options';
import React from 'react';

interface SelectionTerminalBarProps {
  selectedPath: DecisionTreeNode[];
  activeLabel?: string | null;
}

// A lightweight terminal-style status bar fixed to the bottom of the viewport
export default function SelectionTerminalBar({ selectedPath, activeLabel }: SelectionTerminalBarProps) {
  const parts: Array<{ text: string; dim?: boolean; pending?: boolean }> = [];
  selectedPath.forEach((node) => parts.push({ text: node.label }));
  if (activeLabel && !selectedPath.map(n => n.label).includes(activeLabel)) {
    parts.push({ text: activeLabel, pending: true });
  }

  return (
    <div
      id="selection-terminal-bar"
  className="fixed bottom-0 left-0 right-0 z-[100] bg-gradient-to-r from-zinc-900/95 via-black/90 to-zinc-900/95 backdrop-blur-sm border-t border-emerald-500/40 font-mono text-xs md:text-sm px-3 md:px-5 py-2 flex items-center gap-3 overflow-x-auto whitespace-nowrap shadow-[0_-4px_12px_rgba(0,0,0,0.65)] outline outline-pink-500/40"
      aria-live="polite"
    >
      <span className="text-emerald-400 shrink-0 font-semibold">Selections:</span>
      {parts.length === 0 ? (
        <span className="text-white/50 italic">(none yet &mdash; activate a zone)</span>
      ) : (
        <div className="flex items-center gap-2">
          {parts.map((part, i) => (
            <React.Fragment key={i}>
              <span
                className={
                  part.pending
                    ? 'text-amber-300 animate-pulse font-medium'
                    : 'text-white font-medium'
                }
              >
                {part.text}
              </span>
              {i < parts.length - 1 && <span className="text-emerald-500/50">&gt;</span>}
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
