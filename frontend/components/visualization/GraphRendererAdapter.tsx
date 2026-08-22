"use client";

import dynamic from "next/dynamic";
import { GraphErrorBoundary, RelationshipTableFallback } from "./GraphErrorBoundary";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";

// Both touch the DOM/canvas — client-only, same pattern as ECharts/mermaid.
// Each gets its own loading placeholder so the OTHER engine's bundle cost is
// never paid unless that engine is actually the one selected.
const CytoscapeGraph = dynamic(() => import("./CytoscapeGraph").then((m) => m.CytoscapeGraph), {
  ssr: false,
  loading: () => <GraphLoadingPlaceholder />,
});
const G6Graph = dynamic(() => import("./G6Graph").then((m) => m.G6Graph), {
  ssr: false,
  loading: () => <GraphLoadingPlaceholder />,
});

function GraphLoadingPlaceholder() {
  return <div className="my-4 h-[360px] min-w-0 animate-pulse rounded-2xl border border-line bg-soft shadow-sm" />;
}

// "Auto" mode keeps Cytoscape for small relationship diagrams and selects
// G6 once the supplied graph is large enough for its layout/runtime strengths
// to matter. A named G6/Cytoscape request in the backend spec takes priority,
// followed by the deployment-wide environment override.
const AUTO_G6_NODE_THRESHOLD = 8;

type GraphEngineName = "cytoscape" | "g6";

function resolveEngine(nodeCount: number, preferred?: GraphEngineName | "auto" | null): GraphEngineName {
  if (preferred === "g6" || preferred === "cytoscape") return preferred;
  const override = (process.env.NEXT_PUBLIC_GRAPH_RENDERER ?? "auto").toLowerCase();
  if (override === "g6" || override === "cytoscape") return override;
  return nodeCount >= AUTO_G6_NODE_THRESHOLD ? "g6" : "cytoscape";
}

/**
 * Renderer-neutral entry point for EVIDENCE_GRAPH — the backend emits one
 * graph specification independent of frontend library; this component
 * alone decides which library actually draws it. Selection: an env-level
 * override (NEXT_PUBLIC_GRAPH_RENDERER=g6|cytoscape) forces one engine;
 * otherwise "auto" mode (default) picks by node count. If the selected
 * engine throws, fall back to the OTHER engine (not straight to a table);
 * if that also throws, fall back to the plain relationship table — never
 * retried, permanently for this mount (spec §19's full chain).
 */
export function GraphRendererAdapter({
  nodes, edges, preferredEngine,
}: { nodes: VisualizationGraphNode[]; edges: VisualizationGraphEdge[]; preferredEngine?: GraphEngineName | "auto" | null }) {
  const primary = resolveEngine(nodes.length, preferredEngine);
  const secondary: GraphEngineName = primary === "g6" ? "cytoscape" : "g6";

  const secondaryEl = secondary === "g6" ? <G6Graph nodes={nodes} edges={edges} /> : <CytoscapeGraph nodes={nodes} edges={edges} />;
  const primaryEl = primary === "g6" ? <G6Graph nodes={nodes} edges={edges} /> : <CytoscapeGraph nodes={nodes} edges={edges} />;

  return (
    <GraphErrorBoundary
      failedRenderer={primary}
      fallbackRenderer={secondary}
      fallback={
        <GraphErrorBoundary
          failedRenderer={secondary}
          fallbackRenderer="table"
          fallback={<RelationshipTableFallback nodes={nodes} edges={edges} />}
        >
          {secondaryEl}
        </GraphErrorBoundary>
      }
    >
      {primaryEl}
    </GraphErrorBoundary>
  );
}
