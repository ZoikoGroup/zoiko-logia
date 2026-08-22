import { ArrowRight, ChevronDown, Sparkles } from "lucide-react";

export function ExploreFurther({
  questions,
  onFollowUp,
}: {
  questions: string[];
  onFollowUp?: (question: string) => void;
}) {
  if (questions.length === 0) return null;

  return (
    <details className="group/explore mt-2 rounded-xl border border-line/80 bg-panel">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-ink transition hover:bg-soft">
        <span className="flex items-center gap-2">
          <Sparkles size={14} className="text-brand" />
          Explore further
          <span className="rounded-full bg-soft px-1.5 py-0.5 text-[10px] font-semibold text-muted">{questions.length}</span>
        </span>
        <ChevronDown size={15} className="text-muted transition-transform group-open/explore:rotate-180" />
      </summary>
      <div className="border-t border-line p-1.5">
        {questions.map((question) =>
          onFollowUp ? (
            <button
              key={question}
              type="button"
              onClick={() => onFollowUp(question)}
              className="group flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-ink transition hover:bg-soft"
            >
              <span>{question}</span>
              <ArrowRight size={14} className="shrink-0 text-brand" />
            </button>
          ) : (
            // No handler wired up (e.g. a shared/exported read-only view) —
            // stays visually present but inert, not hidden.
            <div
              key={question}
              className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm text-ink"
            >
              <span>{question}</span>
              <ArrowRight size={14} className="shrink-0 text-brand" />
            </div>
          ),
        )}
      </div>
    </details>
  );
}
