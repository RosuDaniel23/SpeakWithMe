interface SummaryModalProps {
  summary: string;
  countdown: number | null;
}

export function SummaryModal({ summary, countdown }: SummaryModalProps) {
  return (
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-black pointer-events-auto">
      <div className="max-w-3xl w-full px-12 flex flex-col gap-10 items-center">
        <p className="text-4xl md:text-5xl leading-relaxed text-center text-white font-bold">
          {summary}
        </p>
        {countdown !== null && (
          <p className="text-2xl text-white/60 text-center">
            Returning to menu in {countdown}…
          </p>
        )}
      </div>
    </div>
  );
}
