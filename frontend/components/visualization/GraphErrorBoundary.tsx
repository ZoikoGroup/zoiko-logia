"use client";

import { Component, type ReactNode } from "react";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";
import { trackVisualizationInteraction } from "@/lib/telemetry";

/**
 * Generic catch-and-fall-back boundary for ONE graph engine (spec §19 chain:
 * "G6 -> Cytoscape -> relationship table -> text"). A class component
 * because catching render-time errors needs getDerivedStateFromError — no
 * hook equivalent exists. GraphRendererAdapter nests two of these: the
 * outer's fallback is the secondary engine (itself wrapped in one more
 * boundary), whose own fallback is the plain relationship table — so a
 * throw degrades one step at a time, never straight to the table, and never
 * retries the engine that just failed.
 */
export class GraphErrorBoundary extends Component<
  {
    failedRenderer: string;
    fallbackRenderer: string;
    fallback: ReactNode;
    children: ReactNode;
    /** Telemetry category for the thing being rendered — "graph" (default,
     * EVIDENCE_GRAPH/Cytoscape/G6) or "flow" (PROCESS_FLOW/X6/Mermaid). This
     * boundary's fallback mechanics are identical either way; only the
     * telemetry label differs. */
    category?: "graph" | "flow";
  },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    trackVisualizationInteraction("engine_fallback", this.props.category ?? "graph", {
      renderer: this.props.failedRenderer,
      detail: { from: this.props.failedRenderer, to: this.props.fallbackRenderer },
    });
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Terminal fallback (spec §19's last real-rendering step before text) —
 * a plain HTML table, which can't itself fail the way a canvas/WebGL
 * renderer can. */
export function RelationshipTableFallback({
  nodes, edges,
}: { nodes: VisualizationGraphNode[]; edges: VisualizationGraphEdge[] }) {
  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Relationships</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Table fallback</span></header>
      <div className="min-w-0 overflow-x-auto border-t border-line p-3 sm:p-4"><table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr>
            <th className="border border-line px-2 py-1 font-semibold text-ink">Source</th>
            <th className="border border-line px-2 py-1 font-semibold text-ink">Relationship</th>
            <th className="border border-line px-2 py-1 font-semibold text-ink">Target</th>
          </tr>
        </thead>
        <tbody>
          {edges.map((e, i) => (
            <tr key={i}>
              <td className="border border-line px-2 py-1 text-ink">{nodes.find((n) => n.id === e.source)?.label ?? e.source}</td>
              <td className="border border-line px-2 py-1 text-muted">{e.type.replace(/_/g, " ")}</td>
              <td className="border border-line px-2 py-1 text-ink">{nodes.find((n) => n.id === e.target)?.label ?? e.target}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </section>
  );
}
