import { ArrowRight } from "lucide-react";

export function ExploreFurther({
  questions,
  onFollowUp,
}: {
  questions: string[];
  onFollowUp?: (question: string) => void;
}) {
  if (questions.length === 0) return null;

  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="text-xs font-bold uppercase tracking-wider text-muted">Explore further</p>
      <div className="mt-2.5 flex flex-wrap gap-2">
        {questions.map((question) =>
          onFollowUp ? (
            <button
              key={question}
              type="button"
              onClick={() => onFollowUp(question)}
              className="group flex items-center gap-2 rounded-full border border-line bg-panel px-4 py-2 text-left text-sm text-ink transition hover:border-brand/40 hover:bg-brand/5"
            >
              <span>{question}</span>
              <ArrowRight size={14} className="shrink-0 text-brand" />
            </button>
          ) : (
            // No handler wired up (e.g. a shared/exported read-only view) —
            // stays visually present but inert, not hidden.
            <div
              key={question}
              className="flex items-center gap-2 rounded-full border border-line bg-panel px-4 py-2 text-sm text-ink"
            >
              <span>{question}</span>
              <ArrowRight size={14} className="shrink-0 text-brand" />
            </div>
          ),
        )}
      </div>
    </div>
  );
}
