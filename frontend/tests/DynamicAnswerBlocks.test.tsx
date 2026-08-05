import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DynamicAnswerBlocks } from "@/components/DynamicAnswerBlocks";
import type { ComposedAnswer } from "@/lib/api";

vi.mock("@/components/AnswerVisualizations", () => ({
  AnswerVisualizations: () => <div data-testid="visualization">chart</div>,
}));
vi.mock("@/components/CalculationWidget", () => ({
  CalculationWidget: () => <div data-testid="calculation">calculation</div>,
}));

const base: ComposedAnswer = { text: "Legacy answer", citations: [], limitations: [] };

describe("DynamicAnswerBlocks", () => {
  it("keeps legacy answers renderable when blocks are absent", () => {
    render(
      <DynamicAnswerBlocks
        answer={base}
        queryId="q1"
        renderMarkdown={(text) => <p>{text}</p>}
        onFollowUp={vi.fn()}
      />,
    );
    expect(screen.getByText("Legacy answer")).toBeInTheDocument();
  });

  it("renders the backend block order and governed resources", () => {
    const answer: ComposedAnswer = {
      ...base,
      response_mode: "compound",
      presentation: {
        layout: "data_visualization", table_count: 1, has_steps: false,
        charts: [], guides: [], graphs: [], sections: [], follow_up_questions: [],
      },
      blocks: [
        { id: "text", type: "markdown", content: "Planned answer", resource_ids: [] },
        { id: "chart", type: "visualization", resource_ids: ["chart-1"] },
        { id: "limits", type: "limitations", content: "Supplied data only.", resource_ids: [] },
      ],
    };
    render(
      <DynamicAnswerBlocks
        answer={answer}
        queryId="q1"
        renderMarkdown={(text) => <p>{text}</p>}
        onFollowUp={vi.fn()}
      />,
    );
    expect(screen.getByText("Planned answer")).toBeInTheDocument();
    expect(screen.getByTestId("visualization")).toBeInTheDocument();
    expect(screen.getByText("Supplied data only.")).toBeInTheDocument();
  });
});
