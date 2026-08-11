/**
 * Reads a CSS custom property's live computed value at call time. Canvas/SVG
 * renderers (ECharts, Mermaid) can't consume `var(--x)` directly — they need
 * a literal color string — so anything theme-aware that reaches one of them
 * must go through this instead of a hardcoded hex value.
 */
export function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
