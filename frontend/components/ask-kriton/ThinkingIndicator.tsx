"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";

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
    <div className="flex items-center gap-3 py-2">
      <div className="kriton-ledger-card relative h-12 w-12 shrink-0 overflow-hidden rounded-xl border border-brand/25 bg-panel p-2" aria-hidden="true">
        <div className="kriton-ledger-scan absolute inset-x-1 top-1 h-px bg-brand/70" />
        <div className="space-y-1.5 pt-0.5">
          <div className="kriton-ledger-row h-1.5 w-7 rounded-full" />
          <div className="kriton-ledger-row h-1.5 w-5 rounded-full" />
          <div className="kriton-ledger-row h-1.5 w-6 rounded-full" />
        </div>
        <Check className="kriton-ledger-check absolute bottom-0.5 right-0.5 text-ok" size={15} strokeWidth={3} />
      </div>
      <div className="min-w-0 flex-1">
        <p key={step} className="kriton-animate-status text-sm font-semibold text-ink">
          {STATUS_STEPS[step]}
        </p>
        <div className="mt-2.5 flex items-center gap-1.5" aria-hidden="true">
          {STATUS_STEPS.map((_, i) => (
            <span key={i} className={`h-1 flex-1 max-w-8 rounded-full transition-colors duration-300 ${i <= step ? "bg-brand" : "bg-soft"}`} />
          ))}
        </div>
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {STATUS_STEPS[step]}
      </span>
    </div>
  );
}
