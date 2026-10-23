import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ChartOffer, VisualizationSpec } from "@/lib/api";

// The real renderer draws with ECharts/Recharts; here it only shows which
// spec it was given.
vi.mock("@/components/AnswerRenderer", () => ({
  VisualizationRenderer: ({ viz }: { viz: VisualizationSpec }) => <div>drawn: {viz.title} ({viz.type})</div>,
}));

import { ChartOfferPrompt } from "@/components/ask-kriton/ChartOfferPrompt";

const offer: ChartOffer = {
  chart_type: "line",
  title: "Cash flow (USD) by year",
  question: "Show this as a line chart.",
  reason: "The figures run over time, so a line shows the trend.",
};

const pie = {
  id: "q-offer",
  type: "DONUT",
  family: "COMPOSITION",
  renderer: "ECHARTS",
  title: "Amount recognised in 2026 by performance obligation",
  unit: "%",
  donut: [
    { label: "Software licence", value: 58.82, is_estimated: false },
    { label: "Implementation services", value: 23.53, is_estimated: false },
    { label: "Technical support", value: 17.65, is_estimated: false },
  ],
} as unknown as VisualizationSpec;

const withChart: ChartOffer = {
  chart_type: "pie",
  title: "Amount recognised in 2026 by performance obligation",
  question: "Show this as a pie chart.",
  reason: "The parts add up to a whole, so a pie shows each one's share.",
  chart: pie,
};

describe("chart offer", () => {
  it("asks before drawing, naming the chart and why it fits", () => {
    render(<ChartOfferPrompt offer={offer} onAccept={() => {}} />);
    expect(screen.getByText(/Would you like to see/)).toBeTruthy();
    expect(screen.getByText("Cash flow (USD) by year")).toBeTruthy();
    expect(screen.getByText(offer.reason)).toBeTruthy();
  });

  it("opens the chart under the answer without sending a question", () => {
    const onAccept = vi.fn();
    render(<ChartOfferPrompt offer={withChart} onAccept={onAccept} />);
    expect(screen.queryByTestId("chart-offer-chart")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show pie chart" }));
    expect(screen.getByTestId("chart-offer-chart").textContent).toContain(
      "drawn: Amount recognised in 2026 by performance obligation (DONUT)",
    );
    expect(onAccept).not.toHaveBeenCalled();
  });

  it("hides the chart on a second click", () => {
    render(<ChartOfferPrompt offer={withChart} onAccept={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pie chart" }));
    const hide = screen.getByRole("button", { name: "Hide chart" });
    expect(hide.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(hide);
    expect(screen.queryByTestId("chart-offer-chart")).toBeNull();
    expect(screen.getByRole("button", { name: "Show pie chart" })).toBeTruthy();
  });

  it("can show its chart in a read-only view, since that sends nothing", () => {
    render(<ChartOfferPrompt offer={withChart} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pie chart" }));
    expect(screen.getByTestId("chart-offer-chart")).toBeTruthy();
  });

  it("an older offer without a chart still sends its question", () => {
    const onAccept = vi.fn();
    render(<ChartOfferPrompt offer={offer} onAccept={onAccept} />);
    fireEvent.click(screen.getByRole("button", { name: "Show line chart" }));
    expect(onAccept).toHaveBeenCalledWith("Show this as a line chart.");
  });

  it("goes away when declined and sends nothing", () => {
    const onAccept = vi.fn();
    render(<ChartOfferPrompt offer={withChart} onAccept={onAccept} />);
    fireEvent.click(screen.getByRole("button", { name: "No thanks" }));
    expect(screen.queryByText(/Would you like to see/)).toBeNull();
    expect(onAccept).not.toHaveBeenCalled();
  });

  it("an older offer without a chart is informational only in a read-only view", () => {
    render(<ChartOfferPrompt offer={offer} />);
    expect(screen.queryByRole("button", { name: "Show line chart" })).toBeNull();
  });
});
