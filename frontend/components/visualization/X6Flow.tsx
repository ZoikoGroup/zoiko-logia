"use client";

import { useEffect, useRef, useState } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { cssVar } from "@/lib/css-var";
import { useTheme } from "@/components/shell/ThemeProvider";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";
import { WORKFLOW_HEIGHT } from "@/components/visualization/vizSize";

const STAGE_WIDTH = 140;
const STAGE_HEIGHT = 44;
const STAGE_GAP = 90;

/**
 * X6 interactive-workflow renderer (spec §10). PROCESS_FLOW specs are always
 * a simple linear chain (extraction.py only extracts an ordered arrow chain
 * — see its docstring), so this lays nodes out left-to-right at fixed
 * spacing rather than pulling in a separate layout package for a shape
 * that's already known.
 */
export function X6Flow({
  nodes,
  edges,
}: {
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<import("@antv/x6").Graph | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  // cssVar() below reads a snapshot at construction time — re-run on theme
  // toggle so a dark<->light switch doesn't leave stale colors, same fix as
  // CytoscapeGraph.tsx/MermaidFlow.tsx.
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    (async () => {
      try {
        const { Graph } = await import("@antv/x6");
        if (cancelled || !containerRef.current) return;

        const brand = cssVar("--brand", "#16799a");
        const ink = cssVar("--ink", "#17211f");
        const line = cssVar("--line", "#eef3f2");
        const panel = cssVar("--panel", "#ffffff");

        const graph = new Graph({
          container: containerRef.current,
          width: containerRef.current.clientWidth || 600,
          height: WORKFLOW_HEIGHT,
          panning: true,
          mousewheel: { enabled: true, minScale: 0.4, maxScale: 2 },
          interacting: { nodeMovable: false },
        });
        graphRef.current = graph;

        resizeObserver = new ResizeObserver(() => {
          if (!containerRef.current) return;
          graph.resize(containerRef.current.clientWidth || 600, WORKFLOW_HEIGHT);
          graph.zoomToFit({ padding: 24, maxScale: 1 });
        });
        resizeObserver.observe(containerRef.current);

        nodes.forEach((n, i) => {
          graph.addNode({
            id: n.id,
            x: i * (STAGE_WIDTH + STAGE_GAP),
            y: 60,
            width: STAGE_WIDTH,
            height: STAGE_HEIGHT,
            label: n.label,
            attrs: {
              body: { fill: panel, stroke: brand, strokeWidth: 1.5, rx: 10, ry: 10 },
              label: { fill: ink, fontSize: 12, fontWeight: 600 },
            },
          });
        });
        edges.forEach((e) => {
          graph.addEdge({
            source: e.source,
            target: e.target,
            attrs: {
              line: { stroke: line, strokeWidth: 1.5, targetMarker: { name: "block", width: 8, height: 6 } },
            },
          });
        });

        graph.zoomToFit({ padding: 24, maxScale: 1 });
        graph.on("node:click", ({ node }: { node: { id: string } }) => setSelected(node.id));

      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      graphRef.current?.dispose();
      graphRef.current = null;
    };
  }, [nodes, edges, theme]);

  if (failed) {
    // Fallback tier below X6 (Mermaid was removed — see FlowRendererAdapter's
    // docstring): numbered steps, not a bare error, so the structure is
    // still legible even when the interactive renderer can't draw it.
    return (
      <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Interactive workflow</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Fallback</span></header>
        <ol className="list-decimal space-y-1 border-t border-line p-4 pl-8 text-xs text-ink">{nodes.map((n) => <li key={n.id}>{n.label}</li>)}</ol>
      </section>
    );
  }

  const selectedNode = nodes.find((n) => n.id === selected);
  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Interactive workflow</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Process</span></header>
      <div className="relative">
        <div
          ref={containerRef}
          role="img"
          aria-label={`Interactive process flow with ${nodes.length} stages`}
          className="w-full border-t border-line"
          style={{ height: WORKFLOW_HEIGHT }}
        />
        <div className="absolute right-2 top-2 flex flex-col gap-1">
          <button
            type="button" title="Zoom in" aria-label="Zoom in on process flow"
            onClick={() => graphRef.current?.zoom(0.2)}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomIn size={13} />
          </button>
          <button
            type="button" title="Zoom out" aria-label="Zoom out of process flow"
            onClick={() => graphRef.current?.zoom(-0.2)}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomOut size={13} />
          </button>
          <button
            type="button" title="Fit to view" aria-label="Fit process flow to view"
            onClick={() => graphRef.current?.zoomToFit({ padding: 24, maxScale: 1 })}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <Maximize2 size={13} />
          </button>
        </div>
      </div>
      {selectedNode && (
        <div className="border-t border-line bg-soft px-3 py-2 text-xs text-ink sm:px-4">
          <span className="font-semibold">Stage: {selectedNode.label}</span>
        </div>
      )}
    </section>
  );
}
