"use client";

import { getAuthToken, recordVisualizationEvent, type VisualizationTelemetryRequest } from "@/lib/api";

const DEDUP_WINDOW_MS = 2000;
const MAX_TRACKED_KEYS = 200;
const recentlySent = new Map<string, number>();

function dedupKey(payload: VisualizationTelemetryRequest): string {
  return [payload.event_name, payload.query_id ?? "", payload.active_chart_type ?? "", payload.original_chart_type ?? ""].join("|");
}

/** Dynamic Visualization Selection v4 — fire-and-forget telemetry.
 *
 * Never awaited by callers, never throws, never delays chart rendering,
 * view switching, exports, or saving — those are all real user-visible
 * outcomes that must succeed or fail entirely independently of whether
 * this network call ever completes. A short per-event dedup window absorbs
 * a rapid double click or an unrelated React rerender without suppressing
 * two genuinely distinct interactions (e.g. switching to view A, then back
 * to the original view, a few seconds apart). */
export function emitVisualizationEvent(payload: VisualizationTelemetryRequest): void {
  const key = dedupKey(payload);
  const now = Date.now();
  const last = recentlySent.get(key);
  if (last !== undefined && now - last < DEDUP_WINDOW_MS) return;
  recentlySent.set(key, now);
  if (recentlySent.size > MAX_TRACKED_KEYS) {
    for (const [trackedKey, sentAt] of recentlySent) {
      if (now - sentAt > DEDUP_WINDOW_MS) recentlySent.delete(trackedKey);
    }
  }

  const token = getAuthToken();
  if (!token) return;
  void recordVisualizationEvent(token, payload).catch(() => {
    // Telemetry must never surface as a user-facing error — silently drop.
  });
}
