import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echarts-stub" />,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    recordVisualizationEvent: vi.fn(async () => {}),
  };
});

// jsdom has no canvas rasterizer, so the SVG->PNG step is stubbed; the point
// of these tests is the wiring (does Copy image reach the clipboard with the
// figure's bytes), not the rasterization itself.
const pngBlob = new Blob(["fake-png"], { type: "image/png" });
let rasterizes = true;
vi.mock("@/lib/export/svgToPngBlob", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/export/svgToPngBlob")>();
  return {
    ...actual,
    serializeContainerSvg: () => "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    svgToPngBlob: async () => (rasterizes ? pngBlob : null),
  };
});

const copiedImages: Blob[] = [];
let clipboardAcceptsImages = true;
vi.mock("@/lib/presentation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/presentation")>();
  return {
    ...actual,
    writeImageToClipboard: async (blob: Blob) => {
      if (!clipboardAcceptsImages) throw new Error("no ClipboardItem");
      copiedImages.push(blob);
    },
  };
});

const { AnswerVisualizations } = await import("@/components/AnswerVisualizations");

function makePresentation(chart: PresentationChart): AnswerPresentation {
  return {
    layout: "data_visualization", table_count: 1, has_steps: false,
    charts: [chart], guides: [], graphs: [], sections: [], follow_up_questions: [],
  };
}

function makeChart(overrides: Partial<PresentationChart> = {}): PresentationChart {
  return {
    chart_id: "c-copy", title: "Department comparison", unit: "$",
    domain: "general", summary_mode: "total", type: "grouped_bar",
    x_axis_label: "Department",
    value_format: "currency", currency_code: "USD", decimal_places: 0,
    categories: ["Payroll", "Technology"],
    series: [
      { name: "Budget", values: ["150000", "60000"], unit: "$" },
      { name: "Actual", values: ["158000", "72000"], unit: "$" },
    ],
    alternatives: [],
    original_chart_type: "grouped_bar",
    analytical_intent: "comparison",
    selection_source: "deterministic_default",
    schema_version: "1.0",
    ...overrides,
  };
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  copiedImages.length = 0;
  rasterizes = true;
  clipboardAcceptsImages = true;
});

describe("Copy image", () => {
  it("puts the rendered figure on the clipboard as a PNG", async () => {
    const user = userEvent.setup();
    render(<AnswerVisualizations presentation={makePresentation(makeChart())} />);

    await user.click(screen.getByRole("button", { name: /copy image/i }));
    await waitFor(() => expect(copiedImages).toHaveLength(1));
    expect(copiedImages[0].type).toBe("image/png");
    await waitFor(() => expect(screen.getAllByText("Done").length).toBeGreaterThan(0));
  });

  it("reports a failure when the figure cannot be rasterized", async () => {
    rasterizes = false;
    const user = userEvent.setup();
    render(<AnswerVisualizations presentation={makePresentation(makeChart())} />);

    await user.click(screen.getByRole("button", { name: /copy image/i }));
    await waitFor(() => expect(screen.getByText(/failed/i)).toBeTruthy());
    expect(copiedImages).toHaveLength(0);
  });

  it("reports a failure when the browser cannot copy images", async () => {
    clipboardAcceptsImages = false;
    const user = userEvent.setup();
    render(<AnswerVisualizations presentation={makePresentation(makeChart())} />);

    await user.click(screen.getByRole("button", { name: /copy image/i }));
    await waitFor(() => expect(screen.getByText(/failed/i)).toBeTruthy());
  });
});

describe("Copy table", () => {
  it("copies the table as TSV so it pastes into spreadsheet columns", async () => {
    const user = userEvent.setup();
    render(<AnswerVisualizations presentation={makePresentation(makeChart())} />);

    await user.click(screen.getByRole("button", { name: /copy table/i }));
    await waitFor(() => expect(screen.getByText("Copied")).toBeTruthy());

    const copied = await navigator.clipboard.readText();
    const [header, payroll, technology] = copied.split("\n");
    expect(header).toBe("Department\tBudget\tActual");
    // Tabs, not commas — a comma-separated paste lands in one cell.
    expect(payroll).toBe("Payroll\t$150,000\t$158,000");
    expect(technology).toBe("Technology\t$60,000\t$72,000");
  });

  it("falls back to the series name header when the chart has no x-axis label", async () => {
    const user = userEvent.setup();
    render(<AnswerVisualizations presentation={makePresentation(makeChart({ x_axis_label: undefined }))} />);
    await user.click(screen.getByRole("button", { name: /copy table/i }));
    await waitFor(() => expect(screen.getByText("Copied")).toBeTruthy());
    expect((await navigator.clipboard.readText()).split("\n")[0]).toBe("Label\tBudget\tActual");
  });

  it("leaves a cell blank rather than printing NaN for a non-numeric value", async () => {
    const user = userEvent.setup();
    const chart = makeChart({
      series: [{ name: "Budget", values: ["150000", "n/a"], unit: "$" }],
    });
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    await user.click(screen.getByRole("button", { name: /copy table/i }));
    await waitFor(() => expect(screen.getByText("Copied")).toBeTruthy());

    const rows = (await navigator.clipboard.readText()).split("\n");
    expect(rows[2]).toBe("Technology\t");
    expect(rows.join("\n")).not.toMatch(/NaN/);
  });

  it("does not crash the figure when the clipboard is denied", async () => {
    const user = userEvent.setup();
    render(<AnswerVisualizations presentation={makePresentation(makeChart())} />);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => { throw new Error("denied by permissions policy"); } },
      configurable: true,
    });

    await user.click(screen.getByRole("button", { name: /copy table/i }));
    // Stays on the idle label, and the table it copies from is still rendered.
    expect(screen.getByRole("button", { name: /copy table/i })).toBeTruthy();
    expect(screen.queryByText("Copied")).toBeNull();
  });
});
