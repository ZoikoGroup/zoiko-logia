"use client";

import { ArrowLeftRight, ArrowRight, Check, Clock3, GitBranch, ListTree, Sparkles } from "lucide-react";
import type { AnswerPresentation } from "@/lib/api";
import { DOMAIN_LABELS } from "@/lib/presentationLabels";
import { WorkflowVisualization } from "@/components/WorkflowVisualization";
import { KnowledgeGraphVisualization } from "@/components/KnowledgeGraphVisualization";
import { AnswerChartFigure } from "@/components/AnswerChartFigure";

export function AnswerVisualizations({
  presentation,
  onFollowUp,
  queryId,
  sourceReferences,
  conversationId,
}: {
  presentation: AnswerPresentation;
  onFollowUp?: (question: string) => void;
  queryId?: string;
  sourceReferences?: string[];
  conversationId?: string;
}) {
  const charts = presentation.charts ?? [];
  const guides = presentation.guides ?? [];
  const graphs = presentation.graphs ?? [];
  const sections = presentation.sections ?? [];
  const followUps = presentation.follow_up_questions ?? [];
  if (!charts.length && !guides.length && !graphs.length && sections.length < 2 && !followUps.length) return null;

  return (
    <div className="mt-5 space-y-4" aria-label="Answer presentation">
      {guides.map((guide) => {
        const GuideIcon = guide.type === "timeline" ? Clock3 : guide.type === "checklist" ? Check : guide.type === "decision_flow" ? GitBranch : guide.type === "sequence" ? ArrowLeftRight : ListTree;
        return (
          <section key={guide.guide_id} className="overflow-hidden rounded-2xl border border-line bg-[linear-gradient(145deg,var(--panel),var(--soft))] shadow-[0_8px_30px_rgba(16,24,40,.06)]">
            <div className="h-1 bg-[linear-gradient(90deg,var(--brand),var(--info),var(--ok))]" aria-hidden="true" />
            <div className="p-4 sm:p-5">
            <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-muted">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand/10 text-brand"><GuideIcon size={15} aria-hidden="true" /></span>
              {guide.title}
            </h3>
            <div className="mt-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-brand">{DOMAIN_LABELS[guide.domain ?? "general"]}</div>
            {guide.renderer !== "html" ? <div className="mt-4 overflow-hidden rounded-xl border border-line/80 bg-panel"><WorkflowVisualization guide={guide} queryId={queryId} sourceReferences={sourceReferences} /></div> : <ol className={`mt-4 ${guide.type === "timeline" ? "grid gap-3 sm:grid-cols-2" : guide.type === "process" ? "grid gap-3 sm:grid-cols-2 lg:grid-cols-3" : guide.type === "decision_flow" ? "mx-auto grid max-w-2xl gap-0" : "overflow-hidden rounded-xl border border-line/80 bg-panel shadow-sm divide-y divide-line/70"}`}>
              {guide.items.map((item, index) => (
                <li key={`${guide.guide_id}-${index}`} className={`relative flex gap-3 text-xs leading-5 text-ink ${guide.type === "timeline" ? "group min-h-24 overflow-hidden rounded-xl border border-line/70 bg-panel p-4 pl-16 shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1.5 before:bg-[linear-gradient(var(--brand),var(--info))]" : guide.type === "checklist" ? "items-center bg-panel px-4 py-3.5 transition hover:bg-soft" : `rounded-xl border border-line/70 bg-panel/90 p-3.5 shadow-sm transition hover:-translate-y-0.5 hover:border-brand/30 hover:shadow-md ${guide.type === "decision_flow" && index < guide.items.length - 1 ? "mb-7 after:absolute after:left-1/2 after:top-full after:h-7 after:border-l-2 after:border-dashed after:border-brand/35" : ""}`}`}>
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center text-[11px] font-bold ${guide.type === "checklist" ? "rounded-md border-2 border-ok/40 bg-ok/10 text-ok" : guide.type === "timeline" ? "absolute left-5 top-4 rounded-lg bg-brand/10 text-brand ring-0" : "rounded-full bg-brand text-white ring-4 ring-panel"}`}>
                    {guide.type === "checklist" ? <Check size={13} aria-hidden="true" /> : index + 1}
                  </span>
                  <span className={guide.type === "timeline" ? "font-semibold leading-5" : guide.type === "checklist" ? "flex-1 font-medium" : "font-medium"}>{item}</span>
                  {guide.type === "checklist" && <span className="shrink-0 rounded-full bg-soft px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-muted">Review</span>}
                </li>
              ))}
            </ol>}
            </div>
          </section>
        );
      })}

      {graphs.map((graph) => (
        <section key={graph.graph_id} className="overflow-hidden rounded-2xl border border-line bg-[linear-gradient(145deg,var(--panel),var(--soft))] shadow-[0_8px_30px_rgba(16,24,40,.06)]">
          <div className="h-1 bg-[linear-gradient(90deg,var(--brand),var(--info),var(--ok))]" aria-hidden="true" />
          <KnowledgeGraphVisualization graph={graph} queryId={queryId} sourceReferences={sourceReferences} />
        </section>
      ))}

      {sections.length >= 2 && (
        <section className="rounded-2xl border border-line bg-panel p-4">
          <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-muted">
            <Sparkles size={15} className="text-brand" aria-hidden="true" />
            Full-picture coverage
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {sections.map((section, index) => (
              <span key={`${section}-${index}`} className="rounded-full border border-brand/15 bg-brand/5 px-3 py-1.5 text-xs font-medium text-ink">
                {section}
              </span>
            ))}
          </div>
        </section>
      )}

      {charts.map((chart) => (
        <AnswerChartFigure
          key={chart.chart_id}
          chart={chart}
          queryId={queryId}
          sourceReferences={sourceReferences}
          conversationId={conversationId}
        />
      ))}

      {followUps.length > 0 && (
        <section className="border-t border-line/70 pt-4" aria-label="Suggested follow-up questions">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Explore further</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {followUps.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onFollowUp?.(question)}
                disabled={!onFollowUp}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-2 text-left text-xs font-medium text-ink transition hover:border-brand/40 hover:bg-brand/5 disabled:cursor-default"
              >
                {question}
                <ArrowRight size={13} className="shrink-0 text-brand" aria-hidden="true" />
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
