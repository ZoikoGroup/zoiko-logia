import type { Edge, Node } from "@xyflow/react";
import { exportMermaidPng } from "@/lib/export/exportMermaidPng";

const escapeXml = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;",
}[char] ?? char));

/** Creates a deterministic report image from workflow state, independent of
 * viewport zoom/pan, so every node is included in the exported PNG. */
export function exportWorkflowPng(nodes: Node[], edges: Edge[], title: string): Promise<boolean> {
  if (!nodes.length) return Promise.resolve(false);
  const width = Math.max(500, ...nodes.map((node) => node.position.x + 240)) + 40;
  const height = Math.max(260, ...nodes.map((node) => node.position.y + 100)) + 40;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edgeSvg = edges.map((edge) => {
    const source = byId.get(edge.source); const target = byId.get(edge.target);
    if (!source || !target) return "";
    return `<line x1="${source.position.x + 200}" y1="${source.position.y + 36}" x2="${target.position.x}" y2="${target.position.y + 36}" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>`;
  }).join("");
  const nodeSvg = nodes.map((node) => {
    const words = String(node.data.label ?? "").split(/\s+/);
    const lines: string[] = [];
    words.forEach((word) => {
      const current = lines.at(-1) ?? "";
      if (!current || `${current} ${word}`.length > 27) lines.push(word);
      else lines[lines.length - 1] = `${current} ${word}`;
    });
    const text = lines.slice(0, 3).map((line, index) => `<tspan x="12" y="${22 + index * 17}">${escapeXml(line)}</tspan>`).join("");
    return `<g transform="translate(${node.position.x},${node.position.y})"><rect width="200" height="72" rx="10" fill="#f8fafc" stroke="#64748b"/><text font-family="sans-serif" font-size="13" fill="#0f172a">${text}</text></g>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#ffffff"/><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#64748b"/></marker></defs>${edgeSvg}${nodeSvg}</svg>`;
  return exportMermaidPng(svg, title);
}
