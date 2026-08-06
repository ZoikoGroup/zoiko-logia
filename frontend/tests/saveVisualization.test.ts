import { describe, expect, it, vi } from "vitest";

// Mocked without importActual — lib/api.ts also constructs the Supabase
// client at module load, which this test has no reason to touch.
vi.mock("@/lib/api", () => ({
  getAuthToken: () => "test-token",
  createSavedVisualization: vi.fn().mockResolvedValue({ id: "sv-1" }),
}));

const { createSavedVisualization } = await import("@/lib/api");
const { saveVisualization } = await import("@/lib/export/saveVisualization");

describe("saveVisualization", () => {
  it("persists the schema-versioned structured payload, not a snapshot", async () => {
    const graphPayload = {
      graph_id: "g1", title: "Evidence chain", summary: "s", layout: "breadthfirst" as const,
      confidence: 1, nodes: [], edges: [],
    };
    await saveVisualization(
      {
        query_id: "q1", visualization_type: "graph", schema_version: "1.0",
        title: "Evidence chain", summary: "s", payload: graphPayload, source_references: ["REF-1"],
      },
      "idem-key-1",
    );

    expect(createSavedVisualization).toHaveBeenCalledWith(
      "test-token",
      expect.objectContaining({
        visualization_type: "graph",
        schema_version: "1.0",
        payload: graphPayload,
        source_references: ["REF-1"],
      }),
      "idem-key-1",
    );
  });
});
