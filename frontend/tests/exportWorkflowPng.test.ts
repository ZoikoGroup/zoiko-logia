import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/export/exportMermaidPng", () => ({
  exportMermaidPng: vi.fn().mockResolvedValue(true),
}));

const { exportMermaidPng } = await import("@/lib/export/exportMermaidPng");
const { exportWorkflowPng } = await import("@/lib/export/exportWorkflowPng");

describe("exportWorkflowPng", () => {
  it("exports all workflow nodes and connections as SVG-backed PNG", async () => {
    const nodes = [
      { id: "a", position: { x: 0, y: 0 }, data: { label: "Review invoice" } },
      { id: "b", position: { x: 250, y: 0 }, data: { label: "Approve payment" } },
    ];
    const edges = [{ id: "e", source: "a", target: "b" }];
    await expect(exportWorkflowPng(nodes, edges, "Approval workflow")).resolves.toBe(true);
    expect(exportMermaidPng).toHaveBeenCalledWith(expect.stringContaining("Review invoice"), "Approval workflow");
  });

  it("fails safely for an empty workflow", async () => {
    await expect(exportWorkflowPng([], [], "Empty")).resolves.toBe(false);
  });
});
