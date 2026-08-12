"use client";

import { useEffect, useRef, useState } from "react";
import { cssVar } from "@/lib/css-var";
import { useTheme } from "@/components/shell/ThemeProvider";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";
import { GRAPH_HEIGHT } from "@/components/visualization/vizSize";

/**
 * Experimental second evidence-graph renderer (spec §13: "Add G6 as a second
 * graph renderer... use G6 for testing"). Not the production default — see
 * GraphRendererAdapter.tsx's feature flag and benchmark.md for why Cytoscape
 * stays primary until a real benchmark justifies switching (spec §15/§28:
 * "do not migrate merely because G6 is newer").
 */
export function G6Graph({
  nodes,
  edges,
}: {
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<{ kind: "node" | "edge"; label: string; detail: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    let graph: import("@antv/g6").Graph | null = null;
    let resizeObserver: ResizeObserver | null = null;

    (async () => {
      try {
        // Dynamic import: G6 touches the DOM/canvas, never runs on the server.
        const { Graph } = await import("@antv/g6");
        if (cancelled || !containerRef.current) return;

        const brand = cssVar("--brand", "#16799a");
        const ink = cssVar("--ink", "#17211f");
        const line = cssVar("--line", "#eef3f2");
        const gold = cssVar("--gold", "#f3c437");

        graph = new Graph({
          container: containerRef.current,
          width: containerRef.current.clientWidth || 600,
          height: GRAPH_HEIGHT,
          data: {
            nodes: nodes.map((n) => ({ id: n.id, data: { label: n.label, type: n.type } })),
            edges: edges.map((e, i) => ({
              id: `e${i}`,
              source: e.source,
              target: e.target,
              data: { label: e.type.replace(/_/g, " ") },
            })),
          },
          node: {
            style: {
              fill: brand,
              labelText: (d: { data?: { label?: string } }) => d.data?.label ?? "",
              labelFill: ink,
              labelFontSize: 11,
              labelPlacement: "bottom",
              size: 24,
            },
          },
          edge: {
            style: {
              stroke: line,
              labelText: (d: { data?: { label?: string } }) => d.data?.label ?? "",
              labelFill: ink,
              labelFontSize: 9,
              labelBackground: true,
              endArrow: true,
            },
          },
          layout: { type: "force", linkDistance: 90, preventOverlap: true },
          behaviors: ["drag-canvas", "zoom-canvas", "drag-element"],
        });

        // G6 5.x's "node:click"/"edge:click" listeners are typed against the
        // broad IEvent union (which also covers lifecycle events with no
        // target at all), even though these two specific event names always
        // fire an IElementEvent with a real target carrying the element id
        // at runtime (per G6's own docs/examples). A narrow local cast is the
        // pragmatic way to read it back without importing G6's internal
        // graphics types.
        graph.on("node:click", (evt) => {
          const id = (evt as unknown as { target: { id?: string } }).target?.id;
          const n = nodes.find((n2) => n2.id === id);
          if (n) setSelected({ kind: "node", label: n.label, detail: `Entity type: ${n.type}` });
        });
        graph.on("edge:click", (evt) => {
          const id = (evt as unknown as { target: { id?: string } }).target?.id;
          const idx = Number((id ?? "").replace("e", ""));
          const e = edges[idx];
          if (e) setSelected({ kind: "edge", label: e.type.replace(/_/g, " "), detail: `${e.source} → ${e.target}` });
        });

        await graph.render();
        resizeObserver = new ResizeObserver(() => {
          if (!containerRef.current || !graph) return;
          graph.resize(containerRef.current.clientWidth || 600, GRAPH_HEIGHT);
          void graph.fitView({ when: "always", direction: "both" });
        });
        resizeObserver.observe(containerRef.current);
        void gold; // reserved for a future selection-highlight style pass

      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      graph?.destroy();
    };
  }, [nodes, edges, theme]);

  if (failed) {
    return (
      <div className="my-4 rounded-xl border border-dashed border-line bg-soft p-4 text-xs leading-5 text-muted">
        G6 failed to render this graph. Try the Cytoscape renderer instead
        (unset NEXT_PUBLIC_GRAPH_RENDERER, or set it to &quot;cytoscape&quot;).
      </div>
    );
  }

  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Relationship graph</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Evidence</span></header>
      <div
        ref={containerRef}
        role="img"
        aria-label={`Interactive relationship graph with ${nodes.length} nodes and ${edges.length} edges`}
        className="w-full border-t border-line"
        style={{ height: GRAPH_HEIGHT }}
      />
      {selected && (
        <div className="border-t border-line bg-soft px-3 py-2 text-xs text-ink sm:px-4">
          <span className="font-semibold">{selected.kind === "node" ? "Node" : "Edge"}: {selected.label}</span>
          <span className="ml-2 text-muted">{selected.detail}</span>
        </div>
      )}
    </section>
  );
}
