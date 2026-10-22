"use client";

import { useState, useCallback } from "react";
import type { VisualizationSpec } from "@/lib/api";

/**
 * Real, client-only (localStorage) per-chart-type preferences: "prefer
 * table over chart" (state #3 in the chart-states list) and "use this view
 * as my default" (only meaningful for types with a same-shape view
 * alternative — see engineRouting.ts's SAME_SHAPE_VIEW_ALTERNATIVES).
 * Keyed by the backend's own concrete `type` (LINE/BAR/HISTOGRAM/...),
 * which is the precise "shape" this preference is about — no invented
 * "comparison/trend/composition family" taxonomy the backend doesn't
 * itself define. Server-side, cross-device persistence would need a new
 * backend model/endpoint and isn't built yet; this is the honest,
 * currently-buildable slice of that feature.
 */
const PREFER_TABLE_KEY = (type: string) => `kriton:chart-pref:prefer-table:${type}`;
const DEFAULT_VIEW_KEY = (type: string) => `kriton:chart-pref:default-view:${type}`;

function readBool(key: string): boolean {
  if (typeof window === "undefined") return false;
  try { return window.localStorage?.getItem(key) === "1"; } catch { return false; }
}

function readString(key: string): string | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage?.getItem(key) ?? null; } catch { return null; }
}

export function usePreferTable(type: VisualizationSpec["type"]) {
  const [preferTable, setPreferTableState] = useState(() => readBool(PREFER_TABLE_KEY(type)));
  const setPreferTable = useCallback((value: boolean) => {
    setPreferTableState(value);
    if (typeof window !== "undefined") {
      try { window.localStorage?.setItem(PREFER_TABLE_KEY(type), value ? "1" : "0"); } catch { /* Session state still works when storage is blocked. */ }
    }
  }, [type]);
  return [preferTable, setPreferTable] as const;
}

export function useDefaultView(type: VisualizationSpec["type"]) {
  const [defaultView, setDefaultViewState] = useState(() => readString(DEFAULT_VIEW_KEY(type)));
  const setDefaultView = useCallback((value: string) => {
    setDefaultViewState(value);
    if (typeof window !== "undefined") {
      try { window.localStorage?.setItem(DEFAULT_VIEW_KEY(type), value); } catch { /* Session state still works when storage is blocked. */ }
    }
  }, [type]);
  return [defaultView, setDefaultView] as const;
}
