"use client";

import { useEffect, useState } from "react";

const STATUS_STEPS = [
  "Validating your request",
  "Screening safety controls",
  "Checking eligible sources",
  "Preparing a governed response",
];

const STEP_DURATION_MS = 1800;

export function ThinkingIndicator() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setStep((s) => (s + 1) % STATUS_STEPS.length), STEP_DURATION_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="py-1">
      <p key={step} className="kriton-animate-status text-sm font-semibold text-ink">
        {STATUS_STEPS[step]}
      </p>
      <div className="mt-2.5 flex items-center gap-1.5" aria-hidden="true">
        {STATUS_STEPS.map((_, i) => (
          <span
            key={i}
            className={`h-1 flex-1 max-w-8 rounded-full transition-colors duration-300 ${
              i <= step ? "bg-brand" : "bg-soft"
            }`}
          />
        ))}
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {STATUS_STEPS[step]}
      </span>
    </div>
  );
}
