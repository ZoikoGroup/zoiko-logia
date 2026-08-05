import { exportMermaidPng } from "@/lib/export/exportMermaidPng";

/** Export an SVG-based renderer (Recharts or Plotly) through the same
 * hardened SVG-to-canvas path used by Mermaid. */
export function exportSvgElementPng(container: HTMLElement | null, title: string): Promise<boolean> {
  const svg = container?.querySelector("svg");
  if (!svg) return Promise.resolve(false);
  const clone = svg.cloneNode(true) as SVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  return exportMermaidPng(new XMLSerializer().serializeToString(clone), title);
}
