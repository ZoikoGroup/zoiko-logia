import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/export/exportMermaidPng", () => ({
  exportMermaidPng: vi.fn().mockResolvedValue(true),
}));

const { exportMermaidPng } = await import("@/lib/export/exportMermaidPng");
const { exportSvgElementPng } = await import("@/lib/export/exportSvgElementPng");

describe("exportSvgElementPng", () => {
  it("serializes a renderer SVG for PNG conversion", async () => {
    const container = document.createElement("div");
    container.innerHTML = '<svg width="400" height="200"><rect width="20" height="10"/></svg>';
    await expect(exportSvgElementPng(container, "Waterfall")).resolves.toBe(true);
    expect(exportMermaidPng).toHaveBeenCalledWith(expect.stringContaining("<svg"), "Waterfall");
  });

  it("fails safely when the renderer has no SVG", async () => {
    await expect(exportSvgElementPng(document.createElement("div"), "Empty")).resolves.toBe(false);
  });
});
