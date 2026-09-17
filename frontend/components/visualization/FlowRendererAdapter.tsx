"use client";

import dynamic from "next/dynamic";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";

// Both touch the DOM — client-only, same pattern as ECharts.
const X6Flow = dynamic(() => import("./X6Flow").then((m) => m.X6Flow), { ssr: false });
const MermaidFlow = dynamic(() => import("./MermaidFlow").then((m) => m.MermaidFlow), { ssr: false });

/**
 * Renderer-neutral entry point for PROCESS_FLOW (spec §16/§17). Routes
 * between X6 (interactive workflows) and Mermaid (simple/read-only flows)
 * based on `interactive`, decided server-side by orchestrator.py's
 * _build_process_flow_spec (explicit "interactive workflow" request, or
 * stage count above a complexity threshold — spec §11's own routing rule).
 * A numbered-steps/text fallback lives inside each renderer itself if it
 * fails to draw, per spec §19's fallback layer.
 */
export function FlowRendererAdapter({
  nodes,
  edges,
  interactive,
  preferredEngine,
}: {
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
  interactive: boolean;
  preferredEngine?: "mermaid" | "x6" | null;
}) {
  const useX6 = preferredEngine === "x6" || (preferredEngine !== "mermaid" && interactive);
  return useX6 ? <X6Flow nodes={nodes} edges={edges} /> : <MermaidFlow nodes={nodes} edges={edges} />;
}
