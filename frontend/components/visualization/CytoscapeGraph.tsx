"use client";

import { useEffect, useRef, useState } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { cssVar } from "@/lib/css-var";
import { useTheme } from "@/components/shell/ThemeProvider";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";
import { GRAPH_HEIGHT } from "@/components/visualization/vizSize";

function zoomBy(cy: import("cytoscape").Core | null, factor: number) {
  if (!cy) return;
  const centre = { x: cy.width() / 2, y: cy.height() / 2 };
  cy.zoom({ level: cy.zoom() * factor, renderedPosition: centre });
}

/**
 * Primary evidence-graph renderer (spec §12: "Cytoscape remains available
 * until benchmark results justify replacement"). See G6Graph.tsx for the
 * experimental alternative, and GraphRendererAdapter.tsx for the feature
 * flag that picks between them.
 *
 * Node styling is driven by REAL, computed graph structure (degree,
 * root/leaf position) — never by entity `type`, which extraction.py always
 * leaves as the Entity model's "unknown" default (nothing populates it
 * today, so styling by it would be fake differentiation with no real data
 * behind it; see evidence.py's Entity.type field).
 */
export function CytoscapeGraph({
  nodes,
  edges,
}: {
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<import("cytoscape").Core | null>(null);
  const [selected, setSelected] = useState<{ kind: "node" | "edge"; label: string; detail: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const hasRootLeafDistinction = nodes.length > 1 && edges.length > 0;
  // cssVar() below reads a snapshot at construction time, which doesn't
  // auto-follow a later theme toggle the way a live CSS var() reference
  // would — re-running this effect on `theme` change is the explicit
  // re-render trigger that keeps the canvas in sync.
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    (async () => {
      try {
        const { default: cytoscape } = await import("cytoscape");
        if (cancelled || !containerRef.current) return;

        const brand = cssVar("--brand", "#16799a");
        const chart2 = cssVar("--chart-2", "#eb6834");
        const ink = cssVar("--ink", "#17211f");
        const muted = cssVar("--muted", "#667673");
        const edgeColor = cssVar("--muted", "#667673");
        const panel = cssVar("--panel", "#ffffff");
        const gold = cssVar("--gold", "#f3c437");

        // Real, computed structure — never fabricated. A root (in-degree 0)
        // is a natural starting point, same concept as orchestrator.py's own
        // PROCESS_FLOW start-stage check (a node that's never a target). A
        // leaf (out-degree 0) is a terminal entity. Degree drives size so
        // more-connected "hub" entities stand out — real signal, not a
        // fabricated category.
        const inDegree = new Map<string, number>();
        const outDegree = new Map<string, number>();
        for (const n of nodes) {
          inDegree.set(n.id, 0);
          outDegree.set(n.id, 0);
        }
        for (const e of edges) {
          outDegree.set(e.source, (outDegree.get(e.source) ?? 0) + 1);
          inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
        }

        const elements = [
          ...nodes.map((n) => {
            const degree = (inDegree.get(n.id) ?? 0) + (outDegree.get(n.id) ?? 0);
            const isRoot = (inDegree.get(n.id) ?? 0) === 0 && (outDegree.get(n.id) ?? 0) > 0;
            const isLeaf = (outDegree.get(n.id) ?? 0) === 0 && (inDegree.get(n.id) ?? 0) > 0;
            return {
              data: { id: n.id, label: n.label, type: n.type },
              classes: isRoot ? "root" : isLeaf ? "leaf" : "",
              // 26-42px, scaled by real degree — a fixed, honest range so one
              // outlier node can't blow the layout out.
              style: { width: 26 + Math.min(degree, 4) * 4, height: 26 + Math.min(degree, 4) * 4 },
            };
          }),
          ...edges.map((e, i) => ({
            data: { id: `e${i}`, source: e.source, target: e.target, label: e.type.replace(/_/g, " ") },
          })),
        ];

        const cy = cytoscape({
          container: containerRef.current,
          elements,
          minZoom: 0.3,
          maxZoom: 2.5,
          layout: {
            // Directed, hierarchical — EVIDENCE_GRAPH edges are always
            // directed (real audit-trail/ownership chains), so a top-down
            // breadthfirst layout reads as a clean flow, unlike a force-
            // directed layout that tends to scatter small graphs randomly.
            name: "breadthfirst",
            directed: true,
            spacingFactor: 1.3,
            padding: 28,
            animate: false,
          },
          style: [
            {
              selector: "node",
              style: {
                "background-color": brand,
                label: "data(label)",
                color: ink,
                "font-size": 11,
                "text-valign": "bottom",
                "text-margin-y": 6,
                "border-width": 2,
                "border-color": brand,
                "text-wrap": "wrap",
                "text-max-width": "90px",
              },
            },
            // Root: a thicker, distinctly-colored ring — a real starting
            // point (never a target), not a decorative flourish.
            { selector: "node.root", style: { "border-width": 3, "border-color": chart2, "background-color": chart2 } },
            // Leaf: lighter fill — a terminal entity (never a source).
            { selector: "node.leaf", style: { "background-color": muted, "border-color": muted } },
            {
              selector: "edge",
              style: {
                width: 1.5,
                "line-color": edgeColor,
                "target-arrow-color": edgeColor,
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
                label: "data(label)",
                "font-size": 9,
                color: ink,
                "text-background-color": panel,
                "text-background-opacity": 1,
                "text-background-padding": "2px",
              },
            },
            { selector: "node:selected", style: { "background-color": gold, "border-color": gold } },
            { selector: "node.hovered", style: { "border-width": 4 } },
            { selector: "edge.hovered", style: { width: 3, "line-color": brand, "target-arrow-color": brand } },
          ],
        });
        cyRef.current = cy;

        resizeObserver = new ResizeObserver(() => {
          cy.resize();
          cy.fit(undefined, 32);
        });
        resizeObserver.observe(containerRef.current);

        cy.on("tap", "node", (evt) => {
          const n = evt.target.data();
          setSelected({ kind: "node", label: n.label, detail: `Entity: ${n.label}` });
        });
        cy.on("tap", "edge", (evt) => {
          const edge = evt.target.data();
          setSelected({ kind: "edge", label: edge.label, detail: `${edge.source} → ${edge.target}` });
        });
        // Hover feedback so the graph visibly reads as interactive, not just
        // a static image — a discoverability gap, not a capability gap
        // (zoom/pan/click already worked; nothing signalled that they did).
        cy.on("mouseover", "node, edge", (evt) => {
          evt.target.addClass("hovered");
          if (containerRef.current) containerRef.current.style.cursor = "pointer";
        });
        cy.on("mouseout", "node, edge", (evt) => {
          evt.target.removeClass("hovered");
          if (containerRef.current) containerRef.current.style.cursor = "grab";
        });

        cy.ready(() => {
          cy.resize();
          cy.fit(undefined, 32);
        });

      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges, theme]);

  if (failed) {
    throw new Error("Cytoscape failed to initialize");
  }

  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4">
        <h4 className="text-sm font-semibold text-ink">Relationship graph</h4>
        <span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Evidence</span>
      </header>
      <div className="relative">
        <div
          ref={containerRef}
          role="img"
          aria-label={`Interactive relationship graph with ${nodes.length} nodes and ${edges.length} edges`}
          className="w-full border-t border-line"
          style={{ height: GRAPH_HEIGHT, cursor: "grab" }}
        />
        <div className="absolute right-2 top-2 flex flex-col gap-1">
          <button
            type="button" title="Zoom in" aria-label="Zoom in on relationship graph"
            onClick={() => zoomBy(cyRef.current, 1.25)}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomIn size={13} />
          </button>
          <button
            type="button" title="Zoom out" aria-label="Zoom out of relationship graph"
            onClick={() => zoomBy(cyRef.current, 0.8)}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomOut size={13} />
          </button>
          <button
            type="button" title="Fit to view" aria-label="Fit relationship graph to view"
            onClick={() => cyRef.current?.fit(undefined, 32)}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <Maximize2 size={13} />
          </button>
        </div>
      </div>
      {hasRootLeafDistinction && (
        <div className="flex flex-wrap items-center gap-3 border-t border-line px-3 py-2 text-[11px] text-muted sm:px-4">
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: cssVar("--chart-2", "#eb6834") }} /> Starting entity</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: cssVar("--muted", "#667673") }} /> Terminal entity</span>
          <span>Node size reflects number of connections</span>
        </div>
      )}
      {selected && (
        <div className="border-t border-line bg-soft px-3 py-2 text-xs text-ink sm:px-4">
          <span className="font-semibold">{selected.kind === "node" ? "Node" : "Edge"}: {selected.label}</span>
          <span className="ml-2 text-muted">{selected.detail}</span>
        </div>
      )}
    </section>
  );
}
