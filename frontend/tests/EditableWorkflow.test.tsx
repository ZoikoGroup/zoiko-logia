import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PresentationGuide } from "@/lib/api";

// @xyflow/react measures node/viewport size via ResizeObserver, which jsdom
// doesn't implement.
class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  global.ResizeObserver = FakeResizeObserver as unknown as typeof ResizeObserver;
});

const { WorkflowVisualization } = await import("@/components/WorkflowVisualization");

const editableGuide: PresentationGuide = {
  guide_id: "g1",
  type: "process",
  title: "Invoice approval process",
  items: ["Receive invoice", "Review invoice", "Approve invoice"],
  domain: "accounting",
  renderer: "react_flow",
  editable: true,
};

describe("EditableFlow (react_flow editable workflow)", () => {
  it("renders one node per guide step and lets a user add a new step", async () => {
    const user = userEvent.setup();
    render(<WorkflowVisualization guide={editableGuide} />);

    expect(screen.getByText("Receive invoice")).toBeTruthy();
    expect(screen.getByText("Review invoice")).toBeTruthy();
    expect(screen.getByText("Approve invoice")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Add step" }));
    expect(screen.getByText("New draft step")).toBeTruthy();
  });

  it("lets a user select a node, edit its label, and delete it", async () => {
    const user = userEvent.setup();
    render(<WorkflowVisualization guide={editableGuide} />);

    const deleteButton = screen.getByRole("button", { name: "Delete selected" });
    expect(deleteButton).toBeDisabled(); // nothing selected yet

    // A plain click event (not userEvent's full pointer-down/move/up
    // sequence) — @xyflow/react's underlying d3-drag listener reacts to the
    // realistic sequence in jsdom in a way that throws internally, which is
    // a testing-environment quirk unrelated to onNodeClick's own behavior.
    fireEvent.click(screen.getByText("Review invoice"));
    const labelInput = await screen.findByLabelText("Selected workflow step label");
    expect((labelInput as HTMLInputElement).value).toBe("Review invoice");

    await user.clear(labelInput);
    await user.type(labelInput, "Verify invoice");
    expect(screen.getByText("Verify invoice")).toBeTruthy();
    expect(screen.queryByText("Review invoice")).toBeNull();

    expect(deleteButton).not.toBeDisabled();
    await user.click(deleteButton);
    expect(screen.queryByText("Verify invoice")).toBeNull();
    // The other two steps are untouched.
    expect(screen.getByText("Receive invoice")).toBeTruthy();
    expect(screen.getByText("Approve invoice")).toBeTruthy();
  });

  it("shows Download PNG and Save actions, and Save is absent without a queryId", () => {
    render(<WorkflowVisualization guide={editableGuide} />);
    expect(screen.getByRole("button", { name: /download png/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^save$/i })).toBeNull();
  });

  it("shows the Save action once a queryId is supplied", () => {
    render(<WorkflowVisualization guide={editableGuide} queryId="q1" sourceReferences={["REF-1"]} />);
    expect(screen.getByRole("button", { name: /^save$/i })).toBeTruthy();
  });

  it("restores an exact saved layout (flow_nodes/flow_edges) instead of re-deriving positions", () => {
    const savedGuide: PresentationGuide = {
      ...editableGuide,
      flow_nodes: [
        { id: "n1", position: { x: 10, y: 20 }, label: "Custom step A" },
        { id: "n2", position: { x: 300, y: 20 }, label: "Custom step B" },
      ],
      flow_edges: [{ id: "e1", source: "n1", target: "n2" }],
    };
    render(<WorkflowVisualization guide={savedGuide} />);
    expect(screen.getByText("Custom step A")).toBeTruthy();
    expect(screen.getByText("Custom step B")).toBeTruthy();
    // The original guide.items text should NOT appear — flow_nodes took
    // precedence, as WorkflowVisualization.tsx's initialNodes logic intends.
    expect(screen.queryByText("Receive invoice")).toBeNull();
  });
});
