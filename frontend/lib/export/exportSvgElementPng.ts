import { exportMermaidPng } from "@/lib/export/exportMermaidPng";
import { serializeContainerSvg } from "@/lib/export/svgToPngBlob";

/** Export an SVG-based renderer (Recharts or Plotly) through the same
 * hardened SVG-to-canvas path used by Mermaid. */
export function exportSvgElementPng(container: HTMLElement | null, title: string): Promise<boolean> {
  const svg = serializeContainerSvg(container);
  if (!svg) return Promise.resolve(false);
  return exportMermaidPng(svg, title);
}
