import { describe, expect, it, vi, beforeEach } from "vitest";
import type { Core } from "cytoscape";
import { exportCytoscapePng } from "@/lib/export/exportCytoscapePng";

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
});

function fakeCy() {
  return {
    zoom: vi.fn(() => 1.6),
    pan: vi.fn(() => ({ x: 12, y: 34 })),
    fit: vi.fn(),
    viewport: vi.fn(),
    png: vi.fn(() => "data:image/png;base64,AAAA"),
  } as unknown as Core;
}

describe("exportCytoscapePng", () => {
  it("fits the complete graph before export and captures the full view", () => {
    const cy = fakeCy();
    const ok = exportCytoscapePng(cy, "Evidence chain");

    expect(ok).toBe(true);
    expect(cy.fit).toHaveBeenCalled();
    expect((cy.png as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatchObject({ full: true });
    // fit() happened before png() was captured
    const fitOrder = (cy.fit as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    const pngOrder = (cy.png as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    expect(fitOrder).toBeLessThan(pngOrder);
  });

  it("restores the user's original zoom and pan after exporting", () => {
    const cy = fakeCy();
    exportCytoscapePng(cy, "Evidence chain");
    expect(cy.viewport).toHaveBeenCalledWith({ zoom: 1.6, pan: { x: 12, y: 34 } });
  });

  it("returns false without throwing when there is no live Cytoscape instance", () => {
    expect(exportCytoscapePng(null, "title")).toBe(false);
  });
});
