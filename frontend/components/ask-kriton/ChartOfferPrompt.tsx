"use client";

import { useState } from "react";
import { BarChart3, LineChart, PieChart, X } from "lucide-react";
import type { ChartOffer } from "@/lib/api";
import { VisualizationRenderer } from "@/components/AnswerRenderer";

const ICONS = { line: LineChart, bar: BarChart3, pie: PieChart } as const;

/**
 * Kriton suggests a chart for the answer's figures and asks before drawing
 * it. The offer carries the chart itself, built from the answer's own table,
 * so accepting opens it right under the answer: no new question, no model
 * call, and the figures are exactly the table's. (Sending "Show this as a pie
 * chart." with the original question as context charted the question's
 * numbers instead, 23 Oct 2026.) An older saved offer without a chart still
 * sends its question.
 */
export function ChartOfferPrompt({
  offer,
  onAccept,
}: {
  offer: ChartOffer;
  onAccept?: (question: string) => void;
}) {
  const [dismissed, setDismissed] = useState(false);
  const [open, setOpen] = useState(false);
  if (dismissed) return null;
  const Icon = ICONS[offer.chart_type] ?? BarChart3;
  const chart = offer.chart ?? null;
  // Showing a chart that is already here sends nothing, so it is allowed in a
  // read-only view too; sending a question needs onAccept.
  const canShow = chart !== null || Boolean(onAccept);

  return (
    <div className="mt-2">
      <div
        role="group"
        aria-label="Chart suggestion"
        className="flex items-start gap-3 rounded-xl border border-line/80 bg-panel px-3 py-2.5 text-sm text-ink"
      >
        <Icon size={16} className="mt-0.5 shrink-0 text-brand" aria-hidden />
        <div className="min-w-0 flex-1">
          <p>
            Would you like to see <span className="font-semibold">{offer.title}</span> as a {offer.chart_type} chart?
          </p>
          <p className="mt-0.5 text-xs text-muted">{offer.reason}</p>
          {canShow && (
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                aria-expanded={chart ? open : undefined}
                onClick={() => (chart ? setOpen((value) => !value) : onAccept?.(offer.question))}
                className="rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90"
              >
                {chart && open ? "Hide chart" : `Show ${offer.chart_type} chart`}
              </button>
              {!open && (
                <button
                  type="button"
                  onClick={() => setDismissed(true)}
                  className="rounded-lg px-3 py-1.5 text-xs font-semibold text-muted transition hover:bg-soft"
                >
                  No thanks
                </button>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          aria-label="Dismiss chart suggestion"
          onClick={() => setDismissed(true)}
          className="shrink-0 rounded p-0.5 text-muted transition hover:bg-soft"
        >
          <X size={14} />
        </button>
      </div>
      {chart && open && (
        <div data-testid="chart-offer-chart" className="mt-2">
          <VisualizationRenderer viz={chart} />
        </div>
      )}
    </div>
  );
}
