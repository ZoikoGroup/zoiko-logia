"use client";

import { useState } from "react";
import { ArrowRight, ChevronDown, Sparkles } from "lucide-react";

export function ExploreFurther({
  questions,
  onFollowUp,
}: {
  questions: string[];
  onFollowUp?: (question: string) => void;
}) {
  // Collapsed by default. These are suggestions, not part of the answer, and
  // expanded they pushed the composer below the fold on every turn — the count
  // on the header says what is behind it, so nothing is hidden by collapsing.
  const [open, setOpen] = useState(false);

  if (questions.length === 0) return null;

  return (
    <div className="mt-5 overflow-hidden rounded-xl border border-line bg-panel">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition hover:bg-soft/60"
      >
        <Sparkles size={15} className="shrink-0 text-brand" />
        <span className="text-sm font-semibold text-ink">Explore further</span>
        <span className="rounded-full bg-soft px-1.5 py-0.5 text-[10px] font-semibold text-muted">
          {questions.length}
        </span>
        <ChevronDown
          size={16}
          className={`ml-auto shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3">
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
      )}
    </div>
  );
}
