"use client";

import { ReactNode, useEffect, useState } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { useTheme } from "@/components/shell/ThemeProvider";
import { fetchSwimlaneSvg } from "@/lib/diagrams-api";
import type { VisualizationGraphNode } from "@/lib/api";

/**
 * Swimlane renderer for the `swimlane_diagram` capability — one lane per
 * role, drawn by the backend's self-hosted Kroki (PlantUML). The backend
 * builds the PlantUML from the spec's own validated "Role: Step" labels; this
 * component only displays the returned SVG.
 *
 * Shown through <img>, never innerHTML, so nothing inside the SVG can run.
 * Kroki is optional: while loading or on any failure, `fallback` (the
 * ordinary process flow over the same nodes) is rendered instead.
 */
export function SwimlaneDiagram({
  nodes,
  fallback,
}: {
  nodes: VisualizationGraphNode[];
  fallback: ReactNode;
}) {
  const { theme } = useTheme();
  const [zoom, setZoom] = useState(1);
  const labels = nodes.map((n) => n.label);
  const lanes = new Set(labels.map((label) => label.split(":")[0].trim())).size;
  // Each result remembers the request it answers, so a theme switch or new
  // spec reads as "loading" until its own SVG arrives — no reset in the effect.
  const requestKey = `${theme}\n${labels.join("\n")}`;
  const [result, setResult] = useState<{ key: string; svg: string | null }>({ key: "", svg: null });

  useEffect(() => {
    const controller = new AbortController();
    const [requestTheme, ...requestLabels] = requestKey.split("\n");
    fetchSwimlaneSvg(requestLabels, requestTheme as "light" | "dark", controller.signal)
      .then((svg) => setResult({ key: requestKey, svg }))
      .catch(() => {
        if (!controller.signal.aborted) setResult({ key: requestKey, svg: null });
      });
    return () => controller.abort();
  }, [requestKey]);

  const settled = result.key === requestKey;
  const svg = settled ? result.svg : null;
  const failed = settled && result.svg === null;

  if (failed) {
    return (
      <div className="min-w-0">
        {fallback}
        <p className="mt-1 px-1 text-xs leading-5 text-muted">
          The swimlane renderer isn&apos;t available right now, so this shows the same steps as a process flow.
        </p>
      </div>
    );
  }

  if (svg === null) {
    return (
      <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Swimlane</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Process</span></header>
        <div className="h-40 animate-pulse border-t border-line bg-soft" aria-label="Loading swimlane diagram" />
      </section>
    );
  }

  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Swimlane</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Process</span></header>
      <div className="relative">
        <div className="flex min-w-0 justify-center overflow-x-auto border-t border-line p-3 sm:p-4">
          {/* A data-URL SVG from our own backend: next/image adds nothing here,
              and <img> is what keeps any script inside the SVG inert. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
            alt={`Swimlane with ${lanes} lanes and ${nodes.length} steps: ${nodes.map((n) => n.label).join(", ")}`}
            style={{ transform: `scale(${zoom})`, transformOrigin: "top center", transition: "transform 0.15s ease", maxWidth: "none" }}
          />
        </div>
        <div className="absolute right-2 top-2 flex flex-col gap-1">
          <button
            type="button" title="Zoom in" aria-label="Zoom in on swimlane"
            onClick={() => setZoom((z) => Math.min(2.5, z * 1.25))}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomIn size={13} />
          </button>
          <button
            type="button" title="Zoom out" aria-label="Zoom out of swimlane"
            onClick={() => setZoom((z) => Math.max(0.4, z * 0.8))}
            className="rounded-md border border-line bg-panel p-1 text-muted shadow-sm hover:text-ink"
          >
            <ZoomOut size={13} />
          </button>
          <button
            type="button" title="Reset zoom" aria-label="Reset swimlane zoom"
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
