import type { PresentationGraph } from "@/lib/api";
import { downloadCsv, sanitizeFilename } from "@/lib/visualizationExport";

const NODE_HEADERS = ["id", "label", "entity_type", "status", "source_reference"];
const EDGE_HEADERS = ["id", "source", "target", "relationship_type", "label", "direction"];

/** Two CSVs (nodes + edges) covering every validated node and edge in the
 * graph — no ZIP dependency needed for two small files, and each downloads
 * independently so a failure on one doesn't block the other. */
export function exportGraphCsv(graph: PresentationGraph): void {
  const nodeRows = graph.nodes.map((node) => [
    node.id, node.label, node.entity_type, node.status, node.source_reference,
  ]);
  downloadCsv(NODE_HEADERS, nodeRows, sanitizeFilename(`${graph.title}-nodes`, "csv"));

  const edgeRows = graph.edges.map((edge) => [
    edge.id, edge.source, edge.target, edge.relationship_type, edge.label, edge.direction,
  ]);
  downloadCsv(EDGE_HEADERS, edgeRows, sanitizeFilename(`${graph.title}-edges`, "csv"));
}
