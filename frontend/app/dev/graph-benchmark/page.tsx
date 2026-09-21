"use client";

/**
 * G6 vs Cytoscape benchmark harness (spec §15) — internal dev tool, not
 * linked from any nav. Not registered in lib/nav.ts on purpose.
 *
 * IMPORTANT — what this page is and isn't:
 * This generates real synthetic datasets and renders them with the actual
 * production renderers (CytoscapeGraph / G6Graph), instrumented with real
 * browser timing (performance.now(), requestAnimationFrame FPS sampling,
 * performance.memory where Chrome exposes it). It does NOT contain
 * pre-filled or simulated benchmark numbers — there's no way to run a
 * browser session from this environment to produce them. Open this page in
 * an actual browser (Chrome, for performance.memory) and run each dataset
 * size to fill in the table below; the "export" button copies the results
 * as JSON for a written benchmark report.
 *
 * Only make G6 the production default (NEXT_PUBLIC_GRAPH_RENDERER=g6) if
 * these numbers actually justify it (spec §15/§28) — Cytoscape stays default.
 */

import { useCallback, useRef, useState } from "react";
import type { VisualizationGraphEdge, VisualizationGraphNode } from "@/lib/api";

const DATASET_SIZES = [25, 100, 500, 1000, 5000] as const;
type Renderer = "cytoscape" | "g6";

type BenchmarkRun = {
  renderer: Renderer;
  nodeCount: number;
  edgeCount: number;
  renderMs: number;
  avgFps: number;
  heapDeltaMb: number | null;
  timestamp: number;
};

function generateDataset(nodeCount: number): { nodes: VisualizationGraphNode[]; edges: VisualizationGraphEdge[] } {
  const nodes: VisualizationGraphNode[] = Array.from({ length: nodeCount }, (_, i) => ({
    id: `n${i}`,
    label: `Node ${i}`,
    type: "entity",
  }));
  // Connected random graph: each node (after the first) links to 1-3 earlier
  // nodes, so it's a realistic sparse, connected shape rather than isolated dots.
  const edges: VisualizationGraphEdge[] = [];
  for (let i = 1; i < nodeCount; i++) {
    const linkCount = 1 + Math.floor(Math.random() * 3);
    for (let k = 0; k < linkCount; k++) {
      const target = Math.floor(Math.random() * i);
      edges.push({ source: `n${i}`, target: `n${target}`, type: "related_to", directed: true });
    }
  }
  return { nodes, edges };
}

// Samples real frame times via requestAnimationFrame for `durationMs`,
// returning the average FPS actually achieved on this device — not an
// estimate.
function measureFps(durationMs: number): Promise<number> {
  return new Promise((resolve) => {
    let frames = 0;
    let raf = 0;
    const start = performance.now();
    function tick() {
      frames++;
      const elapsed = performance.now() - start;
      if (elapsed < durationMs) {
        raf = requestAnimationFrame(tick);
      } else {
        cancelAnimationFrame(raf);
        resolve((frames / elapsed) * 1000);
      }
    }
    raf = requestAnimationFrame(tick);
  });
}

function heapMb(): number | null {
  const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
  return mem ? mem.usedJSHeapSize / (1024 * 1024) : null;
}

export default function GraphBenchmarkPage() {
  const [nodeCount, setNodeCount] = useState<(typeof DATASET_SIZES)[number]>(100);
  const [renderer, setRenderer] = useState<Renderer>("cytoscape");
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  const run = useCallback(async () => {
    if (!containerRef.current) return;
    setRunning(true);
    containerRef.current.innerHTML = "";
    const { nodes, edges } = generateDataset(nodeCount);
    const heapBefore = heapMb();

    const t0 = performance.now();
    try {
      if (renderer === "cytoscape") {
        const [{ default: cytoscape }] = await Promise.all([import("cytoscape")]);
        const cy = cytoscape({
          container: containerRef.current,
          elements: [
            ...nodes.map((n) => ({ data: { id: n.id, label: n.label } })),
            ...edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target } })),
          ],
          style: [
            { selector: "node", style: { width: 8, height: 8, "background-color": "#16799a" } },
            { selector: "edge", style: { width: 0.5, "line-color": "#ccc" } },
          ],
          layout: { name: "cose", animate: false },
        });
        await new Promise<void>((resolve) => cy.ready(() => resolve()));
      } else {
        const { Graph } = await import("@antv/g6");
        const graph = new Graph({
          container: containerRef.current,
          width: containerRef.current.clientWidth || 800,
          height: 500,
          data: {
            nodes: nodes.map((n) => ({ id: n.id })),
            edges: edges.map((e, i) => ({ id: `e${i}`, source: e.source, target: e.target })),
          },
          node: { style: { size: 8, fill: "#16799a" } },
          edge: { style: { stroke: "#ccc", lineWidth: 0.5 } },
          layout: { type: "force" },
          behaviors: ["drag-canvas", "zoom-canvas"],
        });
        await graph.render();
      }
    } catch (err) {
      setRunning(false);
      alert(`Render failed: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    const renderMs = performance.now() - t0;

    const avgFps = await measureFps(2000);
    const heapAfter = heapMb();

    setRuns((prev) => [
      ...prev,
      {
        renderer,
        nodeCount,
        edgeCount: edges.length,
        renderMs: Math.round(renderMs),
        avgFps: Math.round(avgFps * 10) / 10,
        heapDeltaMb: heapBefore != null && heapAfter != null ? Math.round((heapAfter - heapBefore) * 10) / 10 : null,
        timestamp: Date.now(),
      },
    ]);
    setRunning(false);
  }, [nodeCount, renderer]);

  return (
    <main className="min-h-screen bg-bg p-6 text-ink">
      <h1 className="text-lg font-bold">G6 vs Cytoscape Benchmark Harness</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Dev-only tool (spec §15). Real synthetic datasets, real render/FPS/memory
        instrumentation — no pre-filled numbers. Run each renderer at each size
        in this actual browser, then export the results for the written report.
        Chrome exposes heap memory; other browsers will show a blank memory column.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="text-sm">
          Nodes:{" "}
          <select
            className="rounded border border-line bg-panel px-2 py-1"
            value={nodeCount}
            onChange={(e) => setNodeCount(Number(e.target.value) as (typeof DATASET_SIZES)[number])}
          >
            {DATASET_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Renderer:{" "}
          <select
            className="rounded border border-line bg-panel px-2 py-1"
            value={renderer}
            onChange={(e) => setRenderer(e.target.value as Renderer)}
          >
            <option value="cytoscape">Cytoscape</option>
            <option value="g6">G6</option>
          </select>
        </label>
        <button
          type="button"
          onClick={run}
          disabled={running}
          className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {running ? "Running…" : "Run benchmark"}
        </button>
        {runs.length > 0 && (
          <button
            type="button"
            onClick={() => navigator.clipboard.writeText(JSON.stringify(runs, null, 2))}
            className="rounded-lg border border-line px-4 py-1.5 text-sm font-semibold text-ink"
          >
            Copy results as JSON
          </button>
        )}
      </div>

      <div ref={containerRef} className="mt-4 h-[500px] w-full rounded-xl border border-line bg-panel" />

      {runs.length > 0 && (
        <table className="mt-6 w-full max-w-3xl border-collapse text-left text-xs">
          <thead>
            <tr>
              <th className="border border-line px-2 py-1">Renderer</th>
              <th className="border border-line px-2 py-1">Nodes</th>
              <th className="border border-line px-2 py-1">Edges</th>
              <th className="border border-line px-2 py-1">Render (ms)</th>
              <th className="border border-line px-2 py-1">Avg FPS (2s post-render)</th>
              <th className="border border-line px-2 py-1">Heap Δ (MB)</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r, i) => (
              <tr key={i}>
                <td className="border border-line px-2 py-1">{r.renderer}</td>
                <td className="border border-line px-2 py-1">{r.nodeCount}</td>
                <td className="border border-line px-2 py-1">{r.edgeCount}</td>
                <td className="border border-line px-2 py-1">{r.renderMs}</td>
                <td className="border border-line px-2 py-1">{r.avgFps}</td>
                <td className="border border-line px-2 py-1">{r.heapDeltaMb ?? "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
