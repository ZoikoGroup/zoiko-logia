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
    <div className="min-w-0 py-3" role="status" aria-live="polite">
      <p key={step} className="kriton-animate-status text-sm font-medium text-muted">
        {STATUS_STEPS[step]}
        <span className="kriton-text-cursor ml-1 inline-block h-[1em] w-0.5 translate-y-[2px] rounded-full bg-brand" aria-hidden="true" />
      </p>
    </div>
  );
}
