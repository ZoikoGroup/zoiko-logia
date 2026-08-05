import { describe, expect, it, vi, beforeEach } from "vitest";
import type { CalculationWidget, PresentationGraph } from "@/lib/api";
import { exportChartCsv } from "@/lib/export/exportChartCsv";
import { exportGraphCsv } from "@/lib/export/exportGraphCsv";

const blobs: Blob[] = [];

beforeEach(() => {
  blobs.length = 0;
  URL.createObjectURL = vi.fn((blob: Blob) => {
    blobs.push(blob);
    return `blob:mock-${blobs.length}`;
  });
  URL.revokeObjectURL = vi.fn();
});

const widget: CalculationWidget = {
  formula_id: "current_ratio", formula_name: "Current ratio", formula_display: "Current assets / Current liabilities",
  methodology_reference: "ref", inputs: [], output_label: "Current ratio", output_value: "1.85", output_unit: "ratio",
  chart_type: "line", chart_label: "Current ratio trend", chart_x_label: "Period", chart_y_label: "Ratio",
  chart_points: [
    { x: "2026-01", y: "1.820000" },
    { x: "2026-02", y: "1.850000" },
  ],
  calculation_id: "calc-abc123",
};

const graph: PresentationGraph = {
  graph_id: "g1", title: "Evidence chain", summary: "2 records connected by 1 relationship.",
  layout: "breadthfirst", confidence: 1,
  nodes: [
    { id: "INV-100", label: "INV-100", entity_type: "invoice", status: "open", source_reference: "REF-1", metadata: {} },
    { id: "SUP-1", label: "Acme Supplies", entity_type: "supplier", status: "", source_reference: "", metadata: {} },
  ],
  edges: [
    { id: "e1", source: "INV-100", target: "SUP-1", relationship_type: "issued_by", label: "issued by", direction: "directed" },
  ],
};

describe("exportChartCsv", () => {
  it("preserves the widget's raw Decimal-as-string chart_points values", async () => {
    exportChartCsv(widget);
    expect(blobs).toHaveLength(1);
    const text = await blobs[0].text();
    expect(text).toContain("1.820000");
    expect(text).toContain("1.850000");
    expect(text).not.toMatch(/1\.82\s*ratio|\$/); // never a formatted display string
  });
});

describe("exportGraphCsv", () => {
  it("downloads two CSVs containing every validated node and edge", async () => {
    exportGraphCsv(graph);
    expect(blobs).toHaveLength(2);
    const [nodesCsv, edgesCsv] = await Promise.all(blobs.map((b) => b.text()));

    expect(nodesCsv).toContain("id,label,entity_type,status,source_reference");
    expect(nodesCsv).toContain("INV-100");
    expect(nodesCsv).toContain("Acme Supplies");
    expect(nodesCsv).toContain("REF-1");

    expect(edgesCsv).toContain("id,source,target,relationship_type,label,direction");
    expect(edgesCsv).toContain("issued_by");
    expect(edgesCsv).toContain("directed");
  });
});
