"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { VisualizationSpec } from "@/lib/api";

/**
 * "View" dropdown — same-shape client-side alternatives only (see
 * engineRouting.ts's SAME_SHAPE_VIEW_ALTERNATIVES docstring for why not
 * every backend fallback_order entry is safely offerable here). Switching
 * is 100% local state in the parent (never a refetch, never mutates the
 * original spec) — this component only reports the chosen type upward and
 * announces the switch for screen readers via a visually-hidden live region.
 */
export function ChartViewMenu({
  currentType, alternatives, onSelect,
}: {
  currentType: VisualizationSpec["type"];
  alternatives: VisualizationSpec["type"][];
  onSelect: (type: VisualizationSpec["type"]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");

  if (alternatives.length === 0) return null;

  function choose(type: VisualizationSpec["type"]) {
    setOpen(false);
    onSelect(type);
    setAnnouncement(`View switched to ${type.toLowerCase()} chart`);
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-medium text-muted hover:text-ink"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        View
        <ChevronDown size={12} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-10 mt-1 min-w-[120px] rounded-lg border border-line bg-panel p-1 shadow-lg">
          <button
            type="button" role="menuitemradio" aria-checked={true}
            className="block w-full rounded px-2 py-1 text-left text-xs font-semibold text-ink"
            onClick={() => setOpen(false)}
          >
            {currentType.charAt(0) + currentType.slice(1).toLowerCase()} (current)
          </button>
          {alternatives.map((alt) => (
            <button
              key={alt} type="button" role="menuitemradio" aria-checked={false}
              className="block w-full rounded px-2 py-1 text-left text-xs text-muted hover:bg-soft hover:text-ink"
              onClick={() => choose(alt)}
            >
              {alt.charAt(0) + alt.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
      )}
      <span className="sr-only" role="status" aria-live="polite">{announcement}</span>
    </div>
  );
}
