import type { Core } from "cytoscape";
import { dataUrlToBlob, downloadBlob, sanitizeFilename } from "@/lib/visualizationExport";

/** Fits the whole graph into frame before exporting so the PNG always shows
 * every node, then restores whatever zoom/pan the user had — the export
 * must never leave the on-screen view changed. */
export function exportCytoscapePng(cy: Core | null, title: string): boolean {
  if (!cy) return false;
  const previousZoom = cy.zoom();
  const previousPan = { ...cy.pan() };
  cy.fit(undefined, 30);
  const dataUrl = cy.png({ output: "base64uri", full: true, scale: 2, bg: "#ffffff" });
  cy.viewport({ zoom: previousZoom, pan: previousPan });
  downloadBlob(dataUrlToBlob(dataUrl), sanitizeFilename(title, "png"));
  return true;
}
