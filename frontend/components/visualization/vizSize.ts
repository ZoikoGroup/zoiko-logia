/**
 * Shared canvas height for every visualization renderer (charts, graphs,
 * heatmaps, box plots, scatter) — one constant so every type stays the
 * same size, imported instead of each renderer hardcoding its own number.
 * Sized for an inline chat answer (like ChatGPT/Claude's own inline chart
 * previews) rather than a full-page dashboard tile — legible axis labels,
 * legend and tooltips still fit at this height in both ECharts and
 * Recharts, just without dominating the conversation.
 */
export const CHART_HEIGHT = 300;
export const GRAPH_HEIGHT = 360;
export const WORKFLOW_HEIGHT = 420;
