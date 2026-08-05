"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from "cytoscape";
import { ZoomIn, ZoomOut, Maximize2, RotateCcw, Network } from "lucide-react";
import type { GraphEntityType, GraphNode, PresentationGraph } from "@/lib/api";
import { VisualizationActions } from "@/components/VisualizationActions";
import { exportCytoscapePng } from "@/lib/export/exportCytoscapePng";
import { exportGraphCsv } from "@/lib/export/exportGraphCsv";
import { saveVisualization } from "@/lib/export/saveVisualization";

/** Cytoscape draws labels on a <canvas> — text is never parsed as HTML/JS
 * regardless of content, so a malicious label can only ever render as
 * literal glyphs. This trims/strips markup characters defensively anyway,
 * matching the same convention as WorkflowVisualization.tsx's safeLabel. */
function safeLabel(value: string): string {
  return value.replace(/["<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 120);
}

// Every value below is authored by this file, never interpolated from graph
// data — entity_type/relationship_type only ever act as lookup KEYS into
// these fixed tables, so nothing from the answer text can inject a style or
// script. A shape carries entity identity independent of color, per WCAG
// "don't rely on color alone."
const ENTITY_SHAPE: Record<GraphEntityType, string> = {
  invoice: "round-rectangle",
  receipt: "rectangle",
  purchase_order: "cut-rectangle",
  contract: "barrel",
  ledger_entry: "hexagon",
  source_document: "octagon",
  supplier: "ellipse",
  user: "triangle",
  approval: "star",
  payment: "diamond",
  bank_transaction: "pentagon",
  audit_evidence: "vee",
};

// Four semantic groups reusing this app's existing categorical theme
// (the same --brand/--info/--warn/--ok tokens AnswerVisualizations.tsx uses
// for chart series) rather than inventing a new 12-hue palette.
const ENTITY_COLOR_VAR: Record<GraphEntityType, string> = {
  invoice: "--brand", receipt: "--brand", purchase_order: "--brand", ledger_entry: "--brand",
  payment: "--info", bank_transaction: "--info",
  supplier: "--warn", user: "--warn", approval: "--warn", contract: "--warn",
  source_document: "--ok", audit_evidence: "--ok",
};

// CSS clip-path/border-radius swatches for the legend, matching the family
// of each Cytoscape shape above closely enough to teach the mapping.
const SHAPE_SWATCH_STYLE: Record<GraphEntityType, React.CSSProperties> = {
  invoice: { borderRadius: 3 },
  receipt: {},
  purchase_order: { clipPath: "polygon(18% 0, 100% 0, 100% 100%, 0 100%, 0 18%)" },
  contract: { borderRadius: "45% / 18%" },
  ledger_entry: { clipPath: "polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%)" },
  source_document: { clipPath: "polygon(30% 0, 70% 0, 100% 30%, 100% 70%, 70% 100%, 30% 100%, 0 70%, 0 30%)" },
  supplier: { borderRadius: "50%" },
  user: { clipPath: "polygon(50% 0, 100% 100%, 0 100%)" },
  approval: { clipPath: "polygon(50% 0%, 61% 35%, 98% 35%, 68% 57%, 79% 91%, 50% 70%, 21% 91%, 32% 57%, 2% 35%, 39% 35%)" },
  payment: { clipPath: "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)" },
  bank_transaction: { clipPath: "polygon(50% 0, 100% 38%, 82% 100%, 18% 100%, 0 38%)" },
  audit_evidence: { clipPath: "polygon(0 0, 50% 55%, 100% 0, 100% 28%, 50% 100%, 0 28%)" },
};

function entityLabel(type: string): string {
  return type.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function resolveColor(variable: string): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(variable).trim() || "#888";
}

function buildStylesheet(): StylesheetJson {
  const line = resolveColor("--line");
  const ink = resolveColor("--ink");
  const panel = resolveColor("--panel");
  const bad = resolveColor("--bad");
  const styles: StylesheetJson = [
    {
      selector: "node",
      style: {
        "background-color": (element) => resolveColor(ENTITY_COLOR_VAR[element.data("entityType") as GraphEntityType] ?? "--muted"),
        shape: (element) => (ENTITY_SHAPE[element.data("entityType") as GraphEntityType] ?? "ellipse") as never,
        label: "data(label)",
        color: ink,
        "font-size": 10,
        "text-valign": "bottom",
        "text-margin-y": 6,
        "text-wrap": "wrap",
        "text-max-width": "90px",
        width: 34,
        height: 34,
        "border-width": 2,
        "border-color": panel,
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": line,
        "target-arrow-color": line,
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
    {
      selector: "edge[direction = 'bidirectional']",
      style: { "source-arrow-shape": "triangle", "source-arrow-color": line },
    },
    {
      selector: ".kriton-faded",
      style: { opacity: 0.2 },
    },
    {
      selector: ".kriton-highlighted",
      style: { "border-color": bad, "border-width": 3, opacity: 1 },
    },
    {
      selector: "edge.kriton-highlighted",
      style: { "line-color": bad, "target-arrow-color": bad, "source-arrow-color": bad, width: 2.5, opacity: 1 },
    },
  ];
  return styles;
}

function toElements(graph: PresentationGraph): ElementDefinition[] {
  const nodes: ElementDefinition[] = graph.nodes.map((node) => ({
    data: { id: node.id, label: safeLabel(node.label), entityType: node.entity_type },
  }));
  const edges: ElementDefinition[] = graph.edges.map((edge) => ({
    data: {
      id: edge.id, source: edge.source, target: edge.target,
      label: safeLabel(edge.label), relationshipType: edge.relationship_type, direction: edge.direction,
    },
  }));
  return [...nodes, ...edges];
}

const LAYOUT_OPTIONS: Record<PresentationGraph["layout"], cytoscape.LayoutOptions> = {
  breadthfirst: { name: "breadthfirst", directed: true, spacingFactor: 1.3, padding: 24, animate: false } as cytoscape.LayoutOptions,
  cose: { name: "cose", padding: 24, animate: false, idealEdgeLength: () => 90 } as cytoscape.LayoutOptions,
  concentric: { name: "concentric", padding: 24, animate: false, minNodeSpacing: 30 } as cytoscape.LayoutOptions,
};

type ViewState = "loading" | "ready" | "empty" | "error";

export function KnowledgeGraphVisualization({
  graph, queryId, sourceReferences = [],
}: {
  graph: PresentationGraph;
  queryId?: string;
  sourceReferences?: string[];
}) {
  const reactId = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const idempotencyKeyRef = useRef(crypto.randomUUID());
  const cyRef = useRef<Core | null>(null);
  const initialViewport = useRef<{ zoom: number; pan: cytoscape.Position } | null>(null);
  const [selectedId, setSelectedId] = useState<string>("");
  const [status, setStatus] = useState<ViewState>(graph.nodes.length === 0 ? "empty" : "loading");

  const nodesById = useMemo(() => {
    const map = new Map<string, GraphNode>();
    graph.nodes.forEach((node) => map.set(node.id, node));
    return map;
  }, [graph]);

  const presentEntityTypes = useMemo(
    () => Array.from(new Set(graph.nodes.map((node) => node.entity_type))).sort(),
    [graph],
  );

  const highlight = (nodeId: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("kriton-faded kriton-highlighted");
    if (!nodeId) return;
    const node = cy.getElementById(nodeId);
    if (node.empty()) return;
    const neighborhood = node.closedNeighborhood();
    cy.elements().difference(neighborhood).addClass("kriton-faded");
    neighborhood.addClass("kriton-highlighted");
  };

  useEffect(() => {
    if (graph.nodes.length === 0 || !containerRef.current) return;
    let cy: Core | null = null;
    try {
      cy = cytoscape({
        container: containerRef.current,
        elements: toElements(graph),
        style: buildStylesheet(),
        layout: LAYOUT_OPTIONS[graph.layout] ?? LAYOUT_OPTIONS.cose,
        minZoom: 0.3,
        maxZoom: 2.5,
        wheelSensitivity: 0.25,
      });
      cyRef.current = cy;
      const markReady = () => {
        initialViewport.current = { zoom: cy!.zoom(), pan: { ...cy!.pan() } };
        setStatus("ready");
      };
      cy.on("layoutstop", markReady);
      // Cytoscape can finish a small synchronous layout inside its
      // constructor, before the layoutstop listener above is attached. Its
      // ready callback still runs in both the synchronous and async cases.
      cy.ready(markReady);
      cy.on("tap", "node", (event) => {
        const id = event.target.id();
        setSelectedId(id);
        highlight(id);
      });
      cy.on("tap", (event) => {
        if (event.target === cy) {
          setSelectedId("");
          cy!.elements().removeClass("kriton-faded kriton-highlighted");
        }
      });
    } catch {
      setStatus("error");
    }
    return () => {
      cy?.destroy();
      cyRef.current = null;
    };
  }, [graph]);

  const selectNode = (id: string) => {
    setSelectedId(id);
    highlight(id);
    const cy = cyRef.current;
    if (cy && id) {
      const node = cy.getElementById(id);
      if (!node.empty()) cy.animate({ center: { eles: node } }, { duration: 200 });
    }
  };

  if (status === "empty") {
    return <p className="p-4 text-xs text-muted">No relationship graph could be built from validated records for this answer.</p>;
  }
  if (status === "error") {
    return (
      <div className="p-4 text-xs text-muted">
        <p>The graph could not be rendered. Here is the underlying data:</p>
        <GraphListAlternative graph={graph} />
      </div>
    );
  }

  const selectedNode = selectedId ? nodesById.get(selectedId) ?? null : null;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-ink">
          <Network size={14} className="text-brand" aria-hidden="true" />
          {graph.title}
        </div>
        <div className="flex items-center gap-1" role="toolbar" aria-label="Graph view controls">
          <button type="button" onClick={() => { const cy = cyRef.current; if (cy) cy.zoom(cy.zoom() * 1.2); }}
            className="rounded-lg border border-line p-1.5 text-muted hover:text-ink" aria-label="Zoom in">
            <ZoomIn size={14} aria-hidden="true" />
          </button>
          <button type="button" onClick={() => { const cy = cyRef.current; if (cy) cy.zoom(cy.zoom() / 1.2); }}
            className="rounded-lg border border-line p-1.5 text-muted hover:text-ink" aria-label="Zoom out">
            <ZoomOut size={14} aria-hidden="true" />
          </button>
          <button type="button" onClick={() => cyRef.current?.fit(undefined, 30)}
            className="rounded-lg border border-line p-1.5 text-muted hover:text-ink" aria-label="Fit to view">
            <Maximize2 size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => {
              const cy = cyRef.current;
              const initial = initialViewport.current;
              if (cy && initial) cy.viewport({ zoom: initial.zoom, pan: initial.pan });
              setSelectedId("");
              cy?.elements().removeClass("kriton-faded kriton-highlighted");
            }}
            className="rounded-lg border border-line p-1.5 text-muted hover:text-ink"
            aria-label="Reset view"
          >
            <RotateCcw size={14} aria-hidden="true" />
          </button>
        </div>
      </div>

      <p className="px-4 pt-3 text-xs text-muted">{graph.summary}</p>

      <div className="px-4 pt-3">
        <VisualizationActions
          onDownloadPng={() => exportCytoscapePng(cyRef.current, graph.title)}
          onExportCsv={() => exportGraphCsv(graph)}
          onSave={
            queryId
              ? async () => {
                  const ok = await saveVisualization(
                    {
                      query_id: queryId,
                      visualization_type: "graph",
                      title: graph.title,
                      summary: graph.summary,
                      payload: graph,
                      source_references: sourceReferences,
                    },
                    idempotencyKeyRef.current,
                  );
                  if (ok) idempotencyKeyRef.current = crypto.randomUUID();
                  return ok;
                }
              : undefined
          }
        />
      </div>

      <div className="grid gap-3 p-3 lg:grid-cols-[1fr_240px]">
        <div className="overflow-hidden rounded-xl border border-line/80 bg-panel">
          {status === "loading" && <p className="p-4 text-xs text-muted">Preparing validated graph…</p>}
          <div ref={containerRef} className="h-[360px] w-full" role="img" aria-label={`${graph.title}: ${graph.summary}`} />
        </div>

        <div className="space-y-3">
          <div>
            <label htmlFor={`graph-node-select-${reactId}`} className="text-[10px] font-bold uppercase tracking-wider text-muted">
              Select a record to inspect
            </label>
            <select
              id={`graph-node-select-${reactId}`}
              value={selectedId}
              onChange={(event) => selectNode(event.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-xs"
            >
              <option value="">— Choose a record —</option>
              {graph.nodes.map((node) => (
                <option key={node.id} value={node.id}>{node.label} ({entityLabel(node.entity_type)})</option>
              ))}
            </select>
          </div>

          <div role="region" aria-live="polite" aria-label="Selected record details" className="rounded-lg border border-line bg-soft p-3 text-xs">
            {selectedNode ? (
              <dl className="space-y-1.5">
                <div><dt className="inline font-semibold text-ink">Record: </dt><dd className="inline">{selectedNode.label}</dd></div>
                <div><dt className="inline font-semibold text-ink">Type: </dt><dd className="inline">{entityLabel(selectedNode.entity_type)}</dd></div>
                {selectedNode.status && <div><dt className="inline font-semibold text-ink">Status: </dt><dd className="inline">{selectedNode.status}</dd></div>}
                {selectedNode.source_reference && <div><dt className="inline font-semibold text-ink">Reference: </dt><dd className="inline">{selectedNode.source_reference}</dd></div>}
                {Object.entries(selectedNode.metadata).map(([key, value]) => (
                  <div key={key}><dt className="inline font-semibold text-ink">{key}: </dt><dd className="inline">{value}</dd></div>
                ))}
              </dl>
            ) : (
              <p className="text-muted">Select a record above, or click a node in the graph, to see its details.</p>
            )}
          </div>

          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-muted">Record types</p>
            <ul className="mt-1.5 space-y-1">
              {presentEntityTypes.map((type) => (
                <li key={type} className="flex items-center gap-2 text-[11px] text-ink">
                  <span
                    aria-hidden="true"
                    className="inline-block h-3 w-3 shrink-0"
                    style={{ background: resolveColor(ENTITY_COLOR_VAR[type]), ...SHAPE_SWATCH_STYLE[type] }}
                  />
                  {entityLabel(type)}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <details className="border-t border-line px-4 py-3">
        <summary className="cursor-pointer text-xs font-semibold text-muted">View as list</summary>
        <GraphListAlternative graph={graph} />
      </details>
    </div>
  );
}

function GraphListAlternative({ graph }: { graph: PresentationGraph }) {
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full min-w-[420px] text-left text-[11px]">
        <caption className="sr-only">Relationships in {graph.title}</caption>
        <thead>
          <tr className="text-muted">
            <th scope="col" className="py-1 pr-2 font-semibold">Source</th>
            <th scope="col" className="py-1 pr-2 font-semibold">Relationship</th>
            <th scope="col" className="py-1 pr-2 font-semibold">Target</th>
          </tr>
        </thead>
        <tbody>
          {graph.edges.map((edge) => (
            <tr key={edge.id} className="border-t border-line/60">
              <td className="py-1 pr-2">{nodesById.get(edge.source)?.label ?? edge.source}</td>
              <td className="py-1 pr-2 text-muted">{edge.direction === "bidirectional" ? "↔" : "→"} {edge.label || entityLabel(edge.relationship_type)}</td>
              <td className="py-1 pr-2">{nodesById.get(edge.target)?.label ?? edge.target}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
