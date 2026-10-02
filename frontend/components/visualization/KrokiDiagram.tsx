"use client";

import { ReactNode, useEffect, useState } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { useTheme } from "@/components/shell/ThemeProvider";
import { fetchKrokiSvg, type KrokiKind } from "@/lib/diagrams-api";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";

const TITLES: Record<KrokiKind, { title: string; badge: string }> = {
  swimlane: { title: "Swimlane", badge: "Process" },
  sequence: { title: "Sequence diagram", badge: "Process" },
  gantt: { title: "Gantt chart", badge: "Timeline" },
  bpmn: { title: "BPMN diagram", badge: "Process" },
  erd: { title: "ER diagram", badge: "Data model" },
  activity: { title: "Activity diagram", badge: "UML" },
  state: { title: "State diagram", badge: "UML" },
  timing: { title: "Timing diagram", badge: "UML" },
  class: { title: "Class diagram", badge: "UML" },
  object: { title: "Object diagram", badge: "UML" },
  usecase: { title: "Use case diagram", badge: "UML" },
  component: { title: "Component diagram", badge: "UML" },
  deployment: { title: "Deployment diagram", badge: "UML" },
  package: { title: "Package diagram", badge: "UML" },
};

// Drawn in fixed dark-on-light colors (bpmn.js, PlantUML timing), so these
// keep a white page in dark mode; the other diagrams are themed.
const PAPER_KINDS = new Set<KrokiKind>(["bpmn", "timing"]);

/**
 * Diagrams drawn by the backend's self-hosted Kroki — swimlane, sequence,
 * Gantt, BPMN, ER and the UML diagrams. The backend builds the diagram source from
 * the spec's own validated labels and edges; this component only displays
 * the returned SVG.
 *
 * Shown through <img>, never innerHTML, so nothing inside the SVG can run.
 * Kroki is optional: on any failure, `fallback` (the ordinary flow or graph
 * over the same data) is rendered instead.
 */
export function KrokiDiagram({
  kind,
  nodes,
  edges,
  fallback,
}: {
  kind: KrokiKind;
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
  fallback: ReactNode;
}) {
  const { theme } = useTheme();
  const [zoom, setZoom] = useState(1);
  const labelOf = new Map(nodes.map((n) => [n.id, n.label]));
  const request = JSON.stringify({
    kind,
    theme,
    labels: nodes.map((n) => n.label),
    edges: edges.map((e) => ({ source: labelOf.get(e.source) ?? e.source, target: labelOf.get(e.target) ?? e.target, type: e.type })),
  });
  // Each result remembers the request it answers, so a theme switch or new
  // spec reads as "loading" until its own SVG arrives — no reset in the effect.
  const [result, setResult] = useState<{ key: string; svg: string | null }>({ key: "", svg: null });

  useEffect(() => {
    const controller = new AbortController();
    const body = JSON.parse(request) as { kind: KrokiKind; theme: "light" | "dark"; labels: string[]; edges: { source: string; target: string; type: string }[] };
    fetchKrokiSvg(body.kind, body.labels, body.edges, body.theme, controller.signal)
      .then((svg) => setResult({ key: request, svg }))
      .catch(() => {
        if (!controller.signal.aborted) setResult({ key: request, svg: null });
      });
    return () => controller.abort();
  }, [request]);

  const { title, badge } = TITLES[kind];
  const settled = result.key === request;
  const svg = settled ? result.svg : null;

  if (settled && svg === null) {
    return (
      <div className="min-w-0">
        {fallback}
        <p className="mt-1 px-1 text-xs leading-5 text-muted">
          The {title.toLowerCase()} renderer isn&apos;t available right now, so this shows the same data in the standard view.
        </p>
      </div>
    );
  }

  const header = (
    <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">{title}</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">{badge}</span></header>
  );

  if (svg === null) {
    return (
      <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        {header}
        <div className="h-40 animate-pulse border-t border-line bg-soft" aria-label={`Loading ${title.toLowerCase()}`} />
      </section>
    );
  }

  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      {header}
      <div className="relative">
        <div className={`flex min-w-0 justify-center overflow-x-auto border-t border-line p-3 sm:p-4 ${PAPER_KINDS.has(kind) ? "bg-white" : ""}`}>
          {/* A data-URL SVG from our own backend: next/image adds nothing here,
              and <img> is what keeps any script inside the SVG inert. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
            alt={`${title}: ${nodes.map((n) => n.label).join(", ")}`}
            style={{ transform: `scale(${zoom})`, transformOrigin: "top center", transition: "transform 0.15s ease", maxWidth: "none" }}
          />
        </div>
        <div className="absolute right-2 top-2 flex flex-col gap-1">
          <button
            type="button" title="Zoom in" aria-label={`Zoom in on ${title.toLowerCase()}`}
            onClick={() => setZoom((z) => Math.min(2.5, z * 1.25))}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomIn size={13} />
          </button>
          <button
            type="button" title="Zoom out" aria-label={`Zoom out of ${title.toLowerCase()}`}
            onClick={() => setZoom((z) => Math.max(0.4, z * 0.8))}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomOut size={13} />
          </button>
          <button
            type="button" title="Reset zoom" aria-label={`Reset ${title.toLowerCase()} zoom`}
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
