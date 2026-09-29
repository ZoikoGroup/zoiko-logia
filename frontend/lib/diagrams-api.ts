import { getCurrentAccessToken } from "@/lib/session-token";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";

/** Swimlane SVG rendered server-side by the backend's self-hosted Kroki
 * (backend/app/orchestration/diagram_router.py). Sends only the node labels
 * of a spec the backend already produced — the backend regenerates and
 * validates the PlantUML itself. Throws on any failure; callers fall back to
 * the ordinary process flow. */
export async function fetchSwimlaneSvg(
  labels: string[],
  theme: "light" | "dark",
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${API_URL}/diagrams/swimlane`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getCurrentAccessToken()}` },
    body: JSON.stringify({ labels, theme }),
    signal,
  });
  if (!res.ok) throw new Error(`Swimlane render failed (${res.status})`);
  const body: { svg?: unknown } = await res.json();
  if (typeof body.svg !== "string") throw new Error("Swimlane render returned no SVG");
  return body.svg;
}
