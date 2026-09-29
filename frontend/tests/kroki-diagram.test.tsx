import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KrokiDiagram } from "@/components/visualization/KrokiDiagram";
import { fetchKrokiSvg, krokiKindFor } from "@/lib/diagrams-api";

vi.mock("@/components/shell/ThemeProvider", () => ({ useTheme: () => ({ theme: "light", toggleTheme: () => {} }) }));
vi.mock("@/lib/diagrams-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/diagrams-api")>()),
  fetchKrokiSvg: vi.fn(),
}));

const swimlaneNodes = [
  { id: "Clerk: Raise PO", label: "Clerk: Raise PO", type: "stage" },
  { id: "Manager: Approve PO", label: "Manager: Approve PO", type: "stage" },
];
const swimlaneEdges = [{ source: "Clerk: Raise PO", target: "Manager: Approve PO", type: "next", directed: true }];

describe("KrokiDiagram", () => {
  afterEach(() => vi.mocked(fetchKrokiSvg).mockReset());

  it("maps every Kroki capability and nothing else", () => {
    expect(krokiKindFor("swimlane_diagram")).toBe("swimlane");
    expect(krokiKindFor("sequence_diagram")).toBe("sequence");
    expect(krokiKindFor("gantt_chart")).toBe("gantt");
    expect(krokiKindFor("bpmn_diagram")).toBe("bpmn");
    expect(krokiKindFor("er_diagram")).toBe("erd");
    expect(krokiKindFor("flowchart_basic")).toBeNull();
    expect(krokiKindFor(null)).toBeNull();
  });

  it("shows the Kroki SVG as an image, never as inline markup", async () => {
    vi.mocked(fetchKrokiSvg).mockResolvedValue('<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>');
    const { container } = render(
      <KrokiDiagram kind="swimlane" nodes={swimlaneNodes} edges={swimlaneEdges} fallback={<p>flow fallback</p>} />,
    );

    const image = await screen.findByRole("img", { name: /Swimlane: Clerk: Raise PO, Manager: Approve PO/ });
    expect(image.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(container.querySelector("script")).toBeNull();
    expect(fetchKrokiSvg).toHaveBeenCalledWith(
      "swimlane", ["Clerk: Raise PO", "Manager: Approve PO"],
      [{ source: "Clerk: Raise PO", target: "Manager: Approve PO", type: "next" }], "light", expect.any(AbortSignal),
    );
  });

  it("sends ER edges by entity label, not node id", async () => {
    vi.mocked(fetchKrokiSvg).mockResolvedValue("<svg></svg>");
    render(
      <KrokiDiagram
        kind="erd"
        nodes={[{ id: "c", label: "Customer", type: "entity" }, { id: "i", label: "Invoice", type: "entity" }]}
        edges={[{ source: "c", target: "i", type: "has_many", directed: true }]}
        fallback={<p>graph fallback</p>}
      />,
    );
    await screen.findByRole("img", { name: /ER diagram/ });
    expect(vi.mocked(fetchKrokiSvg).mock.calls[0][2]).toEqual([{ source: "Customer", target: "Invoice", type: "has_many" }]);
  });

  it("falls back to the standard view when Kroki is unavailable", async () => {
    vi.mocked(fetchKrokiSvg).mockRejectedValue(new Error("503"));
    render(<KrokiDiagram kind="gantt" nodes={swimlaneNodes} edges={swimlaneEdges} fallback={<p>flow fallback</p>} />);

    await waitFor(() => expect(screen.getByText("flow fallback")).toBeTruthy());
    expect(screen.getByText(/gantt chart renderer isn.t available/)).toBeTruthy();
  });
});
