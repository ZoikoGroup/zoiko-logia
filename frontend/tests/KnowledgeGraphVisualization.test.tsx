import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type { PresentationGraph } from "@/lib/api";

// Cytoscape draws to a <canvas>, which jsdom doesn't implement — mock the
// library at the boundary so these tests exercise this app's own
// accessibility wiring (the native keyboard-operable <select> and the
// plain-React details/list views) rather than fighting jsdom's canvas gaps.
// This mirrors testing any heavy visualization dependency: mock the library,
// test what the app built around it.
function makeFakeCy() {
  const elements = {
    removeClass: vi.fn(function (this: unknown) { return this; }),
    addClass: vi.fn(function (this: unknown) { return this; }),
    difference: vi.fn(() => elements),
  };
  const fakeNode = { empty: () => false, closedNeighborhood: () => elements };
  const handlers: Record<string, (...args: unknown[]) => void> = {};
  return {
    on: vi.fn((event: string, a: unknown, b?: unknown) => {
      handlers[event] = (b ?? a) as (...args: unknown[]) => void;
    }),
    ready: vi.fn((callback: () => void) => callback()),
    trigger: (event: string, payload?: unknown) => handlers[event]?.(payload),
    zoom: vi.fn(() => 1),
    pan: vi.fn(() => ({ x: 0, y: 0 })),
    fit: vi.fn(),
    viewport: vi.fn(),
    animate: vi.fn(),
    destroy: vi.fn(),
    getElementById: vi.fn(() => fakeNode),
    elements: vi.fn(() => elements),
  };
}

let fakeCy: ReturnType<typeof makeFakeCy>;

vi.mock("cytoscape", () => ({
  default: vi.fn(() => fakeCy),
}));

// Imported after the mock is registered so the component picks it up.
const { KnowledgeGraphVisualization } = await import("@/components/KnowledgeGraphVisualization");

const baseGraph: PresentationGraph = {
  graph_id: "g1",
  title: "Evidence chain",
  summary: "3 records connected by 2 relationships.",
  layout: "breadthfirst",
  confidence: 1,
  nodes: [
    { id: "INV-100", label: "INV-100", entity_type: "invoice", status: "", source_reference: "", metadata: {} },
    { id: "SUP-1", label: "Acme Supplies", entity_type: "supplier", status: "active", source_reference: "REF-3", metadata: { region: "UK" } },
    { id: "PMT-9", label: "PMT-9", entity_type: "payment", status: "", source_reference: "", metadata: {} },
  ],
  edges: [
    { id: "e1", source: "INV-100", target: "SUP-1", relationship_type: "issued_by", label: "issued by", direction: "directed" },
    { id: "e2", source: "PMT-9", target: "INV-100", relationship_type: "matched_to", label: "matched to", direction: "directed" },
  ],
};

async function renderReady(graph: PresentationGraph) {
  fakeCy = makeFakeCy();
  const utils = render(<KnowledgeGraphVisualization graph={graph} />);
  // The component only shows its controls once Cytoscape's layout settles —
  // fire the mocked layoutstop callback to reach the "ready" state.
  fakeCy.trigger("layoutstop");
  await screen.findByLabelText("Select a record to inspect");
  return utils;
}

describe("KnowledgeGraphVisualization", () => {
  it("lets a keyboard user select and inspect a node via the native select control", async () => {
    await renderReady(baseGraph);
    const select = screen.getByLabelText("Select a record to inspect") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT"); // native control — fully keyboard operable, no mouse required

    fireEvent.change(select, { target: { value: "SUP-1" } });

    const details = screen.getByRole("region", { name: "Selected record details" });
    expect(within(details).getByText("Acme Supplies")).toBeTruthy();
    expect(within(details).getByText("Supplier")).toBeTruthy();
    expect(within(details).getByText("REF-3")).toBeTruthy();
    expect(within(details).getByText("UK")).toBeTruthy();
  });

  it("shows a details panel prompt before any node is selected", async () => {
    await renderReady(baseGraph);
    const details = screen.getByRole("region", { name: "Selected record details" });
    expect(details.textContent).toMatch(/select a record/i);
  });

  it("renders a malicious node label as inert text, never as an executable element", async () => {
    const maliciousGraph: PresentationGraph = {
      ...baseGraph,
      nodes: [
        { ...baseGraph.nodes[0], label: '<img src=x onerror=alert(1)>' },
        baseGraph.nodes[1],
        baseGraph.nodes[2],
      ],
    };
    const { container } = await renderReady(maliciousGraph);

    // No script/img element was created from the label — React only ever
    // rendered it as a text node (no dangerouslySetInnerHTML is used
    // anywhere in this component).
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();

    // The raw string is still visible, verbatim, as plain text — proving it
    // was neutralised by rendering, not silently dropped.
    const select = screen.getByLabelText("Select a record to inspect");
    expect(select.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("renders a malicious edge label as inert text in the list alternative", async () => {
    const maliciousGraph: PresentationGraph = {
      ...baseGraph,
      edges: [
        { ...baseGraph.edges[0], label: "<script>alert(1)</script>" },
        baseGraph.edges[1],
      ],
    };
    const { container } = await renderReady(maliciousGraph);

    const summary = screen.getByText("View as list");
    fireEvent.click(summary);

    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("shows an empty-state message and no interactive graph controls when there are no nodes", () => {
    const emptyGraph: PresentationGraph = { ...baseGraph, nodes: [], edges: [] };
    render(<KnowledgeGraphVisualization graph={emptyGraph} />);
    expect(screen.getByText(/no relationship graph could be built/i)).toBeTruthy();
    expect(screen.queryByLabelText("Select a record to inspect")).toBeNull();
  });
});
