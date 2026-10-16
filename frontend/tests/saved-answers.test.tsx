import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ list: vi.fn(), remove: vi.fn(), create: vi.fn(), drafts: vi.fn(), push: vi.fn() }));
vi.mock("@/lib/api", () => ({
  getAuthToken: () => "token", listSavedAnswers: api.list, deleteSavedAnswer: api.remove, createDraft: api.create, listDrafts: api.drafts,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: api.push }) }));
import SavedAnswersPage from "@/app/saved-answers/page";

const answers = [
  { id: "sa1", query_id: "q1", query_text: "IFRS 15 five steps?", answer_text: "Identify the contract first.", risk_level: "HIGH", tags: ["ifrs"], created_at: "2026-10-10T10:00:00Z" },
  { id: "sa2", query_id: "q2", query_text: "Lease term under IFRS 16?", answer_text: "Non-cancellable period plus options.", risk_level: "LOW", tags: [], created_at: "2026-10-12T10:00:00Z" },
];

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.list.mockResolvedValue(answers);
  api.drafts.mockResolvedValue([{ id: "d1", saved_answer_id: "sa1" }]);
});

describe("Saved Answers", () => {
  it("lists saved answers with their risk and draft status", async () => {
    render(<SavedAnswersPage />);
    expect((await screen.findAllByText("IFRS 15 five steps?")).length).toBeGreaterThan(0);
    expect(screen.getByText("Lease term under IFRS 16?")).toBeInTheDocument();
    expect(screen.getAllByText("HIGH").length).toBeGreaterThan(0);
    expect(await screen.findAllByText("Draft created")).not.toHaveLength(0);
    expect(screen.getByText("2 of 2 saved answers shown")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View audit trail/ })).toHaveAttribute("href", "/audit-replay?correlation_id=q1");
  });

  it("filters by a tag collection", async () => {
    render(<SavedAnswersPage />);
    await screen.findByText("Lease term under IFRS 16?");
    fireEvent.click(screen.getByRole("button", { name: "ifrs" }));
    expect(screen.queryByText("Lease term under IFRS 16?")).not.toBeInTheDocument();
    expect(screen.getByText("1 of 2 saved answers shown")).toBeInTheDocument();
  });

  it("creates a draft from the selected answer and opens Drafts & Reports", async () => {
    api.create.mockResolvedValue({ id: "d2" });
    render(<SavedAnswersPage />);
    fireEvent.click(await screen.findByText("Lease term under IFRS 16?"));
    fireEvent.click(screen.getByRole("button", { name: /Create draft/ }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith("token", {
      title: "Lease term under IFRS 16?", content: "Non-cancellable period plus options.", saved_answer_id: "sa2",
    }));
    await waitFor(() => expect(api.push).toHaveBeenCalledWith("/drafts-reports"));
  });

  it("removes the selected answer", async () => {
    api.remove.mockResolvedValue(undefined);
    render(<SavedAnswersPage />);
    await screen.findByText("Lease term under IFRS 16?");
    fireEvent.click(screen.getByRole("button", { name: /Remove/ }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("token", "sa1"));
    await waitFor(() => expect(screen.getByText("1 of 1 saved answers shown")).toBeInTheDocument());
  });

  it("shows an error when the answers cannot be loaded", async () => {
    api.list.mockRejectedValue(new Error("offline"));
    render(<SavedAnswersPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load saved answers from the server.");
  });
});
