import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), sources: vi.fn(), exportDraft: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ getAuthToken: () => "token", listDrafts: api.list, createDraft: api.create, updateDraft: api.update }));
vi.mock("@/lib/drafts-api", () => ({ deleteDraft: api.remove, listDraftSources: api.sources, exportDraft: api.exportDraft }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
import DraftsReportsPage from "@/app/drafts-reports/page";

const memo = {
  id: "d1", title: "VAT memo", content: "## Summary\n\n| Item | Rate |\n| --- | --- |\n| Standard | 20% |",
  status: "Draft", saved_answer_id: "sa1", created_at: "2026-10-13T10:00:00Z", updated_at: "2026-10-13T10:00:00Z",
};
const board = { ...memo, id: "d2", title: "Board report", content: "Quarterly results", status: "Final", saved_answer_id: null };

beforeEach(() => {
  api.list.mockReset().mockResolvedValue([memo, board]);
  api.sources.mockReset().mockResolvedValue([{ title: "VAT rates", url: "https://www.gov.uk/vat-rates" }]);
  api.update.mockReset().mockImplementation(async (_t: string, id: string, payload: object) => ({ ...memo, id, ...payload }));
  api.remove.mockReset().mockResolvedValue(undefined);
  api.exportDraft.mockReset().mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Drafts & Reports", () => {
  it("filters the list by search text and status", async () => {
    render(<DraftsReportsPage />);
    await screen.findByText("VAT memo");
    fireEvent.change(screen.getByLabelText("Search drafts"), { target: { value: "quarterly" } });
    expect(screen.queryByText("VAT memo")).not.toBeInTheDocument();
    expect(screen.getByText("Board report")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search drafts"), { target: { value: "" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Filter by status" })).getByRole("button", { name: "Draft" }));
    expect(screen.getByText("VAT memo")).toBeInTheDocument();
    expect(screen.queryByText("Board report")).not.toBeInTheDocument();
  });

  it("previews formatted text and lists the answer's sources", async () => {
    render(<DraftsReportsPage />);
    fireEvent.click(await screen.findByText("VAT memo"));
    expect(await screen.findByRole("link", { name: /VAT rates/ })).toHaveAttribute("href", "https://www.gov.uk/vat-rates");
    fireEvent.click(screen.getByRole("tab", { name: /Preview/ }));
    const preview = screen.getByTestId("draft-preview");
    expect(within(preview).getByRole("heading", { name: "Summary" })).toBeInTheDocument();
    expect(within(preview).getByRole("table")).toBeInTheDocument();
  });

  it("leaves citation markers out of the preview but keeps them in the text", async () => {
    api.list.mockResolvedValue([{ ...memo, content: "The threshold is £90,000[REF-1]." }]);
    render(<DraftsReportsPage />);
    fireEvent.click(await screen.findByText("VAT memo"));
    expect(screen.getByPlaceholderText("Draft content…")).toHaveValue("The threshold is £90,000[REF-1].");
    fireEvent.click(screen.getByRole("tab", { name: /Preview/ }));
    expect(within(screen.getByTestId("draft-preview")).getByText("The threshold is £90,000.")).toBeInTheDocument();
  });

  it("saves unsaved edits before exporting", async () => {
    render(<DraftsReportsPage />);
    fireEvent.click(await screen.findByText("VAT memo"));
    fireEvent.change(screen.getByPlaceholderText("Draft content…"), { target: { value: "Edited text" } });
    fireEvent.click(screen.getByRole("button", { name: /Word/ }));
    await waitFor(() => expect(api.exportDraft).toHaveBeenCalledWith("d1", "docx"));
    expect(api.update).toHaveBeenCalledWith("token", "d1", { content: "Edited text", status: "Draft" });
    expect(api.update.mock.invocationCallOrder[0]).toBeLessThan(api.exportDraft.mock.invocationCallOrder[0]);
  });

  it("deletes a draft after confirmation and shows a failed export", async () => {
    api.exportDraft.mockRejectedValue(new Error("The draft is empty"));
    render(<DraftsReportsPage />);
    fireEvent.click(await screen.findByText("VAT memo"));
    fireEvent.click(screen.getByRole("button", { name: /PDF/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The draft is empty");
    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("d1"));
    await waitFor(() => expect(screen.queryByText("VAT memo")).not.toBeInTheDocument());
  });
});
