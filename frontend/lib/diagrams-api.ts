import { getCurrentAccessToken } from "@/lib/session-token";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";

export type KrokiKind = "swimlane" | "sequence" | "gantt" | "bpmn" | "erd";

/** Backend capability_id -> diagram drawn by Kroki (backend
 * app/orchestration/kroki_diagrams.py's KROKI_CAPABILITIES). */
const KROKI_KINDS: Record<string, KrokiKind> = {
  swimlane_diagram: "swimlane",
  sequence_diagram: "sequence",
  gantt_chart: "gantt",
  bpmn_diagram: "bpmn",
  er_diagram: "erd",
};

export function krokiKindFor(capabilityId?: string | null): KrokiKind | null {
  return (capabilityId && KROKI_KINDS[capabilityId]) || null;
}

/** SVG rendered server-side by the backend's self-hosted Kroki
 * (backend/app/orchestration/diagram_router.py). Sends only the labels and
 * edges of a spec the backend already produced — the backend regenerates and
 * validates the diagram source itself. Throws on any failure; callers fall
 * back to the ordinary flow or graph. */
export async function fetchKrokiSvg(
  kind: KrokiKind,
  labels: string[],
  edges: { source: string; target: string; type: string }[],
  theme: "light" | "dark",
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${API_URL}/diagrams/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getCurrentAccessToken()}` },
    body: JSON.stringify({ kind, labels, edges, theme }),
    signal,
  });
  if (!res.ok) throw new Error(`Diagram render failed (${res.status})`);
  const body: { svg?: unknown } = await res.json();
  if (typeof body.svg !== "string") throw new Error("Diagram render returned no SVG");
  return body.svg;
}
