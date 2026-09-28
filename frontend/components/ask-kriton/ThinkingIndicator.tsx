"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

const STATUS_STEPS = [
  "Validating your request",
  "Screening safety controls",
  "Checking eligible sources",
  "Preparing a governed response",
];

const STEP_DURATION_MS = 1800;

export function ThinkingIndicator({ message }: { message?: string }) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setStep((s) => Math.min(s + 1, STATUS_STEPS.length - 1)),
      STEP_DURATION_MS
    );
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-3 py-2" role="status" aria-live="polite">
      <Sparkles size={15} className="kriton-stage-icon shrink-0 text-brand" />
      <div className="min-w-0">
        <p key={step} className="kriton-status-change mt-0.5 text-sm font-semibold text-ink">
          {message || STATUS_STEPS[step]}
        </p>
      </div>
      <span className="ml-1 flex items-center gap-1" aria-hidden="true">
        {STATUS_STEPS.map((stage, index) => (
          <span
            key={stage}
            className={`h-1.5 rounded-full transition-all duration-500 ${
              index === step ? "w-4 bg-brand" : index < step ? "w-1.5 bg-ok" : "w-1.5 bg-line"
            }`}
          />
        ))}
      </span>
    </div>
  );
}
