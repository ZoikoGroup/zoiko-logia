import { cssVar } from "@/lib/css-var";

/**
 * Categorical series colors shared by BOTH chart engines — a small,
 * fixed-order, CVD-validated set (see globals.css's --chart-1..6 comment),
 * deliberately SEPARATE from --ok/--warn/--bad/--info: those are reserved
 * for genuine status (e.g. a flagged outlier), never generic "series N"
 * identity. Read live via cssVar() since the canvas engine can't consume
 * var(--x) directly, and re-read on every render so a theme toggle is
 * reflected without a manual re-render trigger for callers that already
 * re-render on theme change.
 *
 * Fixed order, never cycled/regenerated — a 7th series folds into "Other"
 * rather than reusing a slot. Slots 3-6 read below 3:1 contrast on the light
 * panel (see globals.css), so any chart using more than 2 series (e.g.
 * DONUT) must ship a visible legend/labels or a table view — never rely on
 * hue alone for identity past the first two slots.
 */
export function chartPalette(): string[] {
  return [
    cssVar("--chart-1", "#0a6f96"), cssVar("--chart-2", "#eb6834"),
    cssVar("--chart-3", "#1baf7a"), cssVar("--chart-4", "#eda100"),
    cssVar("--chart-5", "#e87ba4"), cssVar("--chart-6", "#008300"),
  ];
}
