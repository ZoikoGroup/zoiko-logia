/**
 * Shared, fire-and-forget visualization-interaction telemetry — one call
 * site for all three visualization categories (chart/graph/flow), so
 * adoption/failure rates are comparable across them. POSTs to
 * /orchestration/telemetry (backend: frontend_telemetry.py). Never awaited
 * by a caller, never throws, never retried — a dropped telemetry call is an
 * acceptable loss (per the interactivity spec), so this must not become a
 * source of UI-blocking or unhandled-rejection noise.
 */
import { getCurrentAccessToken } from "@/lib/session-token";

// Must match lib/api.ts's API_URL exactly (same backend, same fallback).
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";

export type VisualizationTelemetryEvent =
  | "advisor_evaluated" | "view_selected" | "exported_png" | "exported_csv"
  | "saved" | "table_view_opened" | "render_failed" | "engine_fallback"
  | "preference_set" | "interacted";

export type VisualizationTelemetryCategory = "chart" | "graph" | "flow";

export function trackVisualizationInteraction(
  event: VisualizationTelemetryEvent,
  category: VisualizationTelemetryCategory,
  options?: {
    visualizationId?: string;
    visualizationType?: string;
    renderer?: string;
    detail?: Record<string, unknown>;
  },
): void {
  const token = getCurrentAccessToken();
  if (!token || typeof window === "undefined") return;
  fetch(`${API_URL}/orchestration/telemetry`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      event,
      category,
      visualization_id: options?.visualizationId ?? null,
      visualization_type: options?.visualizationType ?? null,
      renderer: options?.renderer ?? null,
      detail: options?.detail ?? {},
    }),
    // A telemetry call outliving the component that fired it (e.g. a fast
    // navigation) is fine — keepalive lets it complete in the background
    // rather than being aborted with the page unload.
    keepalive: true,
  }).catch(() => {
    // Deliberately silent — see module docstring.
  });
}
