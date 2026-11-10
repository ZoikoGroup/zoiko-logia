import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// "Logia platform bugs" (corrections folder, 10 Nov 2026): bugs 2, 3, 4, 6 and 8.
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: () => ({ data: [], error: "", loading: false, signedOut: false, reload: vi.fn() }),
}));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getAuthToken: () => "token", createSource: vi.fn(), approveSourceVersion: vi.fn(), listSources: vi.fn(),
}));
import { SourceLicensingPanel } from "@/components/source-knowledge/SourceLicensingPanel";

describe("Bug 4: the source form names the file types it accepts", () => {
  it("limits the picker and refuses an image before submit", () => {
    render(<SourceLicensingPanel />);
    const picker = screen.getByLabelText("Source document") as HTMLInputElement;
    expect(picker.accept).toBe(".pdf,.docx,.xlsx,.pptx,.csv,.txt,.md");
    expect(screen.getByText("PDF, Word, Excel, PowerPoint, CSV, TXT or Markdown, up to 25 MB.")).toBeInTheDocument();
    fireEvent.change(picker, { target: { files: [new File(["x"], "Screenshot (3492).png", { type: "image/png" })] } });
    expect(screen.getByText(/Screenshot \(3492\)\.png can't be used as a source/)).toBeInTheDocument();
    expect(screen.getByText("Attach file (optional)")).toBeInTheDocument();          // nothing kept
    fireEvent.change(picker, { target: { files: [new File(["x"], "FRS 102.pdf", { type: "application/pdf" })] } });
    expect(screen.getByText("FRS 102.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/can't be used as a source/)).not.toBeInTheDocument();
  });
});

describe("Bugs 2, 3, 6, 8: the page code says what it shows", () => {
  // Source-level checks for markup whose pages need a full API mock to render.
  const read = async (path: string) => (await import("node:fs")).readFileSync(`${process.cwd()}/${path}`, "utf-8");

  it("bug 2: the deadline count and the 7-day note are separate parts that wrap apart", async () => {
    const page = await read("app/compliance-calendar/page.tsx");
    expect(page).toContain("flex flex-wrap items-baseline gap-x-2");
    expect(page).not.toContain("{soon > 0 && <> · <span");
  });

  it("bug 3: the reviewer select keeps a minimum width and a short placeholder", async () => {
    const page = await read("app/workpapers/page.tsx");
    expect(page).toContain("minmax(10rem,1.4fr)");
    expect(page).toContain(">Reviewer: later<");
    expect(page).not.toContain("Reviewer (choose later)</option>");
  });

  it("bug 6: no bare dash where a run, a measurement or a threshold is missing", async () => {
    const page = await read("app/evaluation-gates/page.tsx");
    expect(page).toContain('const NOT_RUN = "Not run"');
    expect(page).toContain(">Not measured<");
    expect(page).toContain(">Info only<");
    expect(page).not.toMatch(/: "—", detail:/);
  });

  it("bug 8: the connection form scrolls into view and focuses its first field", async () => {
    const page = await read("app/integrations/page.tsx");
    expect(page).toContain('scrollIntoView?.({ behavior: "smooth", block: "start" })');
    expect(page).toContain('querySelector("input")?.focus');
  });
});
