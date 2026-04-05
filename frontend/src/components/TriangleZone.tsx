import { type ReactNode, useState } from 'react';
import { type DecisionTreeNode, TOP_ICON_COLOR, RIGHT_ICON_COLOR, BOTTOM_ICON_COLOR, LEFT_ICON_COLOR } from "@/options.tsx";

// DecisionTreeNode with icon already resolved to ReactNode (post iconMap lookup)
export type ResolvedOption = Omit<DecisionTreeNode, 'icon'> & { icon?: ReactNode };

export interface TriangleZoneProps {
  option: ResolvedOption;
  position: "top" | "left" | "right" | "bottom";
  onSelect: (option: ResolvedOption) => void;
  onCancel: () => void;
  isActive: boolean;
  progress: number;
  durationMs?: number; // optional override (defaults to 3000ms)
}

// A single triangular interaction zone formed by clipping a full-rectangle layer to one diagonal triangle.
export function TriangleZone({ option, position, onSelect, onCancel, isActive, progress, durationMs = 3000 }: TriangleZoneProps) {
  const [hovered, setHovered] = useState(false); // 0..1
  const clipPaths: Record<'top' | 'right' | 'bottom' | 'left', string> = {
    top:    'polygon(0% 0%, 50% 50%, 100% 0%)',
    right:  'polygon(100% 0%, 50% 50%, 100% 100%)',
    bottom: 'polygon(100% 100%, 50% 50%, 0% 100%)',
    left:   'polygon(0% 100%, 50% 50%, 0% 0%)',
  };

  const buttonPositions: Record<'top' | 'right' | 'bottom' | 'left', string> = {
    top:    'absolute top-15 left-1/2 -translate-x-1/2 z-10',
    right:  'absolute right-20 top-1/2 -translate-y-1/2 z-10',
    bottom: 'absolute bottom-15 left-1/2 -translate-x-1/2 z-10',
    left:   'absolute left-20 top-1/2 -translate-y-1/2 z-10',
  };

  const positionColors: Record<'top' | 'right' | 'bottom' | 'left', string> = {
    top: TOP_ICON_COLOR,
    right: RIGHT_ICON_COLOR,
    bottom: BOTTOM_ICON_COLOR,
    left: LEFT_ICON_COLOR,
  };

  // Base color for all zones (black background as previously)
  const baseZoneColor = '#000000';

  // Gradient direction for progress (fills from apex toward base side)
  const gradientDir: Record<'top' | 'right' | 'bottom' | 'left', string> = {
    top: 'to bottom',
    right: 'to left',
    bottom: 'to top',
    left: 'to right',
  };

  const buttonFillHex: Record<'top' | 'right' | 'bottom' | 'left', string> = {
    top: '#F5A623',
    right: '#5EEADB',
    bottom: '#fd2a36',
    left: '#2563eb',
  };

  return (
    <div
  className={`absolute inset-0 w-full h-full cursor-pointer transition-all duration-300 ease-in-out ${(isActive || hovered) ? 'z-20' : 'z-10'}`}
      onClick={() => onSelect(option)}
      role="button"
      tabIndex={0}
      aria-label={`Select ${option.label}`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(option);
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => {setHovered(false); onCancel()}}
      style={{
        clipPath: clipPaths[position],
        WebkitClipPath: clipPaths[position],
        background: (() => {
          if (isActive) {
            const localProgress = Math.min(100, Math.max(0, progress)) / 2;
            return `linear-gradient(${gradientDir[position]}, ${buttonFillHex[position]} 0%, ${buttonFillHex[position]} ${localProgress}%, ${baseZoneColor} ${localProgress}%, ${baseZoneColor} 100%)`;
          }
          return baseZoneColor;
        })(),
      }}
    >
      { (
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          <line
            x1="0" y1="0" x2="100" y2="100"
            stroke="rgba(100, 100, 100, 0.75)"
            strokeWidth={hovered || isActive ? 10 : 1}
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1="100" y1="0" x2="0" y2="100"
            stroke="rgba(100, 100, 100, 0.75)"
            strokeWidth={hovered || isActive ? 10 : 1}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      )}
      <div
        className={buttonPositions[position]}
      >
        <div
          className={`w-56 h-56  ${positionColors[position]} text-white rounded-3xl flex flex-col items-center justify-center relative overflow-hidden transition-all duration-300 ease-in-out hover:scale-105 active:scale-95 shadow-2xl ${isActive ? 'ring-8 ring-white shadow-3xl scale-110' : 'ring-4 ring-white/30'}`}
        >
          <div className="flex flex-col items-center gap-4 z-10">
            {option.icon}
            <span className="text-xl md:text-2xl font-bold text-center text-balance px-4">{option.label}</span>
          </div>
          {(isActive || hovered) && (
            <div className="absolute bottom-3 right-4 text-sm font-semibold text-white/90 drop-shadow">
              {Math.round(progress)}%
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default TriangleZone;
