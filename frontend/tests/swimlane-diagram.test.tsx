import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SwimlaneDiagram } from "@/components/visualization/SwimlaneDiagram";
import { fetchSwimlaneSvg } from "@/lib/diagrams-api";

vi.mock("@/components/shell/ThemeProvider", () => ({ useTheme: () => ({ theme: "light", toggleTheme: () => {} }) }));
vi.mock("@/lib/diagrams-api", () => ({ fetchSwimlaneSvg: vi.fn() }));

const nodes = [
  { id: "Clerk: Raise PO", label: "Clerk: Raise PO", type: "stage" },
  { id: "Manager: Approve PO", label: "Manager: Approve PO", type: "stage" },
];

describe("SwimlaneDiagram", () => {
  afterEach(() => vi.mocked(fetchSwimlaneSvg).mockReset());

  it("shows the Kroki SVG as an image, never as inline markup", async () => {
    vi.mocked(fetchSwimlaneSvg).mockResolvedValue('<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>');
    const { container } = render(<SwimlaneDiagram nodes={nodes} fallback={<p>flow fallback</p>} />);

    const image = await screen.findByRole("img", { name: /Swimlane with 2 lanes and 2 steps/ });
    expect(image.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(container.querySelector("script")).toBeNull();
    expect(fetchSwimlaneSvg).toHaveBeenCalledWith(["Clerk: Raise PO", "Manager: Approve PO"], "light", expect.any(AbortSignal));
  });

  it("falls back to the ordinary process flow when Kroki is unavailable", async () => {
    vi.mocked(fetchSwimlaneSvg).mockRejectedValue(new Error("503"));
    render(<SwimlaneDiagram nodes={nodes} fallback={<p>flow fallback</p>} />);

    await waitFor(() => expect(screen.getByText("flow fallback")).toBeTruthy());
    expect(screen.getByText(/swimlane renderer isn.t available/)).toBeTruthy();
  });
});
