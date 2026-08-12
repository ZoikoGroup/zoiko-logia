"use client";

import { useEffect, useRef, useState } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { cssVar } from "@/lib/css-var";
import { useTheme } from "@/components/shell/ThemeProvider";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";

/**
 * Simple/read-only process-flow renderer (spec §11: "Keep Mermaid as
 * simple/fallback flow engine"). This is NOT the LLM-authored ```mermaid
 * text system removed earlier in this session — that let the model write
 * arbitrary diagram syntax freely. This component instead deterministically
 * GENERATES mermaid syntax from the same validated nodes/edges structure
 * X6Flow.tsx renders — the model never produces or sees mermaid syntax.
 * See FlowRendererAdapter.tsx for the X6-vs-Mermaid routing decision.
 */

// Mermaid node IDs must be alnum/underscore; labels go in the bracket text
// instead, so any real-world label content (spaces, punctuation) is safe
// there — only the ID itself needs sanitizing.
function safeId(id: string, index: number): string {
  const cleaned = id.replace(/[^a-zA-Z0-9_]/g, "_");
  // Prefix with the index so distinct IDs that sanitize to the same value
  // (for example `a-b` and `a b`) cannot collapse into one Mermaid node.
  return `n${index}_${cleaned || "node"}`;
}

// Mermaid bracket labels break on unescaped quotes/brackets — strip the
// characters that matter, keep everything else (this is our own generated
// text from real entity/stage names, not user-supplied raw injection, but
// sanitizing defensively costs nothing).
function safeLabel(label: string): string {
  return label.replace(/["[\]{}|]/g, "");
}

function buildMermaidSource(nodes: VisualizationGraphNode[], edges: VisualizationGraphEdge[]): string {
  const idMap = new Map(nodes.map((n, i) => [n.id, safeId(n.id, i)]));
  const lines = ["flowchart LR"];
  nodes.forEach((n) => {
    lines.push(`  ${idMap.get(n.id)}["${safeLabel(n.label)}"]`);
  });
  edges.forEach((e) => {
    const source = idMap.get(e.source);
    const target = idMap.get(e.target);
    if (source && target) lines.push(`  ${source} --> ${target}`);
  });
  return lines.join("\n");
}

export function MermaidFlow({
  nodes,
  edges,
}: {
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(1);
  // Mermaid's theme config is read once at render time (it bakes colors
  // into the generated SVG) — re-run on theme toggle so a dark<->light
  // switch doesn't leave a stale-colored diagram, same fix as
  // CytoscapeGraph.tsx's own theme dependency.
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        // Themed from the SAME CSS custom properties as the rest of the
        // app — never Mermaid's own default palette — so a flowchart looks
        // like part of Kriton, not a generic embedded diagram, and follows
        // light/dark mode like everything else.
        mermaid.initialize({
          startOnLoad: false,
          theme: "base",
          securityLevel: "strict",
          // Native vector text, not embedded HTML labels — foreignObject
          // text can't be reliably rasterized to a canvas for PNG export in
          // every browser.
          flowchart: { htmlLabels: false, curve: "basis" },
          themeVariables: {
            primaryColor: cssVar("--soft", "#f7faf8"),
            primaryTextColor: cssVar("--ink", "#17211f"),
            primaryBorderColor: cssVar("--brand", "#16799a"),
            lineColor: cssVar("--line", "#c7d0ce"),
            textColor: cssVar("--ink", "#17211f"),
            mainBkg: cssVar("--soft", "#f7faf8"),
            nodeBorder: cssVar("--brand", "#16799a"),
            clusterBkg: cssVar("--panel", "#ffffff"),
            edgeLabelBackground: cssVar("--panel", "#ffffff"),
            fontFamily: "inherit",
            fontSize: "13px",
          },
        });
        const id = `kriton-flow-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, buildMermaidSource(nodes, edges));
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [nodes, edges, theme]);

  if (failed) {
    // Fallback tier below Mermaid (spec §19: "Mermaid -> numbered steps ->
    // text") — same as X6Flow.tsx's own failure fallback.
    return (
      <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Process flow</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Fallback</span></header>
        <ol className="list-decimal space-y-1 border-t border-line p-4 pl-8 text-xs text-ink">{nodes.map((n) => <li key={n.id}>{n.label}</li>)}</ol>
      </section>
    );
  }

  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Process flow</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Process</span></header>
      <div className="relative">
        <div
          className="flex min-w-0 justify-center overflow-x-auto border-t border-line p-3 sm:p-4"
          role="img"
          aria-label={`Process flow with ${nodes.length} stages`}
        >
          <div ref={ref} style={{ transform: `scale(${zoom})`, transformOrigin: "top center", transition: "transform 0.15s ease" }} />
        </div>
        <div className="absolute right-2 top-2 flex flex-col gap-1">
          <button
            type="button" title="Zoom in" aria-label="Zoom in on process flow"
            onClick={() => setZoom((z) => Math.min(2.5, z * 1.25))}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomIn size={13} />
          </button>
          <button
            type="button" title="Zoom out" aria-label="Zoom out of process flow"
            onClick={() => setZoom((z) => Math.max(0.4, z * 0.8))}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomOut size={13} />
          </button>
          <button
            type="button" title="Reset zoom" aria-label="Reset process flow zoom"
            onClick={() => setZoom(1)}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <Maximize2 size={13} />
          </button>
        </div>
      </div>
    </section>
  );
}
