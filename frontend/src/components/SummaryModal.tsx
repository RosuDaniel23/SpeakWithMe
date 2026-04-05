interface SummaryModalProps {
  summary: string;
  onDismiss: () => void;
}

export function SummaryModal({ summary, onDismiss }: SummaryModalProps) {
  const handleCopy = () => {
    navigator.clipboard.writeText(summary).catch(() => {});
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-6">
      <div className="bg-white text-black rounded-3xl shadow-2xl max-w-2xl w-full p-10 flex flex-col gap-6">
        <h2 className="text-2xl font-bold text-center text-gray-800">
          Patient Summary
        </h2>
        <p className="text-xl leading-relaxed text-center text-gray-900 font-medium">
          {summary}
        </p>
        <div className="flex gap-4 justify-center mt-2">
          <button
            onClick={handleCopy}
            className="px-6 py-3 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-800 font-semibold text-lg transition-colors"
          >
            Copy
          </button>
          <button
            onClick={onDismiss}
            className="px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-lg transition-colors"
          >
            New Message
          </button>
        </div>
      </div>
    </div>
  );
}
