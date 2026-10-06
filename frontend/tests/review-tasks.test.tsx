import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ list: vi.fn(), evidence: vi.fn(), resolve: vi.fn() }));
vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {}, getAuthToken: () => "token",
  listReviewCases: api.list, getReviewEvidence: api.evidence, resolveReviewCase: api.resolve,
}));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("@/components/AnswerRenderer", () => ({ AnswerRenderer: () => <div>Draft answer</div> }));
import ReviewTasksPage from "@/app/review-tasks/page";

beforeEach(() => {
  api.list.mockReset().mockResolvedValue({ cases: [{ id: "rc1", query_id: "q1", query_text: "VAT rate?", draft_answer: "The rate is 20%.", status: "open", source: "escalation", reason: "Check evidence", created_at: "2026-01-01" }], counts: { open: 1 } });
  api.evidence.mockReset().mockResolvedValue([{ bundle_id: "b1", passage_id: "p1", source_version_id: "v1", title: "HMRC VAT", locator: "standard rate", content: "Official rate: 20%.", url: "https://www.gov.uk/vat-rates" }]);
  api.resolve.mockReset().mockResolvedValue({ gold_case_id: null });
});

describe("review workflow", () => {
  it("shows the recorded evidence and requires facts before approval", async () => {
    render(<ReviewTasksPage />);
    expect(await screen.findByText("Official rate: 20%." )).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("button", { name: "Save decision" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Required key facts/), { target: { value: "20%" } });
    expect(screen.getByRole("button", { name: "Save decision" })).toBeEnabled();
  });
  it("requests evidence with a note while keeping the case actionable", async () => {
    render(<ReviewTasksPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Request better evidence" }));
    const save = screen.getByRole("button", { name: "Save decision" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Note/), { target: { value: "Need the effective date." } });
    fireEvent.click(save);
    await waitFor(() => expect(api.resolve).toHaveBeenCalledWith("token", "rc1", expect.objectContaining({ decision: "needs_evidence", note: "Need the effective date." })));
    expect(await screen.findByText(/case remains in the queue/)).toBeInTheDocument();
  });
});
