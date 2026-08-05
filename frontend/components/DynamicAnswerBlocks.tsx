"use client";

import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { AnswerVisualizations } from "@/components/AnswerVisualizations";
import { CalculationWidget } from "@/components/CalculationWidget";
import type { ComposedAnswer } from "@/lib/api";

type Props = {
  answer: ComposedAnswer;
  queryId: string;
  conversationId?: string;
  renderMarkdown: (text: string) => ReactNode;
  onFollowUp: (question: string) => void;
};

/** Renders the ordered backend plan while resolving only governed resources
 * already carried by ComposedAnswer. Unknown future blocks fail soft so an
 * older frontend never loses the core answer. */
export function DynamicAnswerBlocks({
  answer,
  queryId,
  conversationId,
  renderMarkdown,
  onFollowUp,
}: Props) {
  const blocks = answer.blocks ?? [];
  const sourceReferences = answer.citations.map((citation) => citation.ref_id);
  const rendered = new Set<string>();

  if (blocks.length === 0) {
    return <>{renderMarkdown(answer.text)}</>;
  }

  return (
    <div className="space-y-4" data-response-mode={answer.response_mode ?? "concise"}>
      {blocks.map((block) => {
        if (rendered.has(block.type) && ["markdown", "visualization", "calculation", "limitations"].includes(block.type)) {
          return null;
        }
        rendered.add(block.type);
        switch (block.type) {
          case "markdown":
            return <div key={block.id}>{renderMarkdown(block.content ?? answer.text)}</div>;
          case "visualization":
            return answer.presentation ? (
              <AnswerVisualizations
                key={block.id}
                presentation={answer.presentation}
                onFollowUp={onFollowUp}
                queryId={queryId}
                sourceReferences={sourceReferences}
                conversationId={conversationId}
              />
            ) : null;
          case "calculation":
            return answer.calculation_widget ? (
              <CalculationWidget
                key={block.id}
                data={answer.calculation_widget}
                queryId={queryId}
                sourceReferences={sourceReferences}
              />
            ) : null;
          case "limitations":
            return block.content ? (
              <aside key={block.id} className="rounded-xl border border-warn/30 bg-warn/5 p-3" aria-label="Answer limitations">
                <div className="flex items-start gap-2 text-sm text-ink">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                  <span>{block.content}</span>
                </div>
              </aside>
            ) : null;
          // Citations retain their existing interactive evidence cards in the
          // parent because opening a source also updates page-level state.
          case "citations":
          case "suggested_actions":
          default:
            return null;
        }
      })}
    </div>
  );
}
