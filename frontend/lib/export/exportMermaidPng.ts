import { downloadBlob, sanitizeFilename } from "@/lib/visualizationExport";
import { svgToPngBlob } from "@/lib/export/svgToPngBlob";

/** Converts the already-rendered, strict-mode Mermaid SVG (see
 * WorkflowVisualization.tsx's MermaidGuide, which is the only source of the
 * `svg` string this ever receives) into a PNG download. The rasterization
 * itself lives in svgToPngBlob so "Copy image" produces a byte-identical
 * figure. Resolves false on any failure instead of throwing, so a broken
 * diagram never crashes the surrounding chat UI. */
export async function exportMermaidPng(svg: string, title: string): Promise<boolean> {
  const blob = await svgToPngBlob(svg);
  if (!blob) return false;
  downloadBlob(blob, sanitizeFilename(title, "png"));
  return true;
}
