import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({
  list: vi.fn(), reviewers: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), submit: vi.fn(), review: vi.fn(),
  add: vi.fn(), remove: vi.fn(), pack: vi.fn(), engagements: vi.fn(), answers: vi.fn(), drafts: vi.fn(), docs: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  getAuthToken: () => "token", listEngagements: api.engagements, listSavedAnswers: api.answers,
  listDrafts: api.drafts, listKritonAttachments: api.docs,
}));
vi.mock("@/lib/workpapers-api", () => ({
  listWorkpapers: api.list, listReviewers: api.reviewers, getWorkpaper: api.get, createWorkpaper: api.create,
  updateWorkpaper: api.update, submitWorkpaper: api.submit, reviewWorkpaper: api.review, addWorkpaperItem: api.add,
  removeWorkpaperItem: api.remove, downloadWorkpaperPack: api.pack,
}));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
import WorkpapersPage from "@/app/workpapers/page";

const base = {
  id: "w1", title: "Revenue recognition FY26", period: "FY2026", status: "open", engagementId: "eng", engagementName: "Zoiko Sema Ltd",
  ownerId: "me", ownerName: "Olivia", reviewerId: "rev", reviewerName: "Ravi", signedOffBy: null, signedOffAt: null, itemCount: 0,
  createdAt: null, updatedAt: null, canEdit: true, canReview: false, notes: "", reviewNote: "", items: [],
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.list.mockResolvedValue([base]);
  api.reviewers.mockResolvedValue([{ id: "rev", name: "Ravi", role: "Audit Partner" }]);
  api.engagements.mockResolvedValue([{ id: "eng", name: "Zoiko Sema Ltd", status: "active", rights_version: "1" }]);
  api.answers.mockResolvedValue([{ id: "sa1", query_text: "IFRS 15 five steps?" }]);
  api.drafts.mockResolvedValue([]);
  api.docs.mockResolvedValue([]);
  api.get.mockResolvedValue(base);
});

describe("Workpapers", () => {
  it("creates a workpaper for a client job with a reviewer", async () => {
    api.create.mockResolvedValue({ ...base, id: "w2", title: "Lease review" });
    render(<WorkpapersPage />);
    fireEvent.change(await screen.findByLabelText("Workpaper title"), { target: { value: "Lease review" } });
    fireEvent.change(screen.getByLabelText("Client job"), { target: { value: "eng" } });
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "rev" } });
    fireEvent.click(screen.getByRole("button", { name: /Create/ }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith({ title: "Lease review", period: "", engagement_id: "eng", reviewer_id: "rev" }));
  });

  it("attaches an item and submits for review as the owner", async () => {
    api.add.mockResolvedValue({ ...base, items: [{ id: "i1", kind: "saved_answer", itemId: "sa1", title: "IFRS 15 five steps?", note: "", missing: false, addedAt: null }] });
    api.submit.mockResolvedValue({ ...base, status: "in_review", canEdit: false });
    render(<WorkpapersPage />);
    fireEvent.click(await screen.findByText("Revenue recognition FY26"));
    fireEvent.change(await screen.findByLabelText("Item to attach"), { target: { value: "saved_answer:sa1" } });
    fireEvent.click(screen.getByRole("button", { name: "Attach" }));
    await waitFor(() => expect(api.add).toHaveBeenCalledWith("w1", "saved_answer", "sa1"));
    fireEvent.click(await screen.findByRole("button", { name: /Submit for review/ }));
    await waitFor(() => expect(api.submit).toHaveBeenCalledWith("w1"));
    expect(await screen.findByText(/Waiting for Ravi to review/)).toBeInTheDocument();
  });

  it("lets the reviewer sign off, and requires a note to return", async () => {
    const inReview = { ...base, status: "in_review", canEdit: false, canReview: true };
    api.get.mockResolvedValue(inReview);
    api.review.mockResolvedValue({ ...inReview, status: "signed_off", canReview: false, signedOffBy: "Ravi", signedOffAt: "2026-10-14T10:00:00Z" });
    render(<WorkpapersPage />);
    fireEvent.click(await screen.findByText("Revenue recognition FY26"));
    expect(await screen.findByRole("button", { name: /Return to owner/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Sign off/ }));
    await waitFor(() => expect(api.review).toHaveBeenCalledWith("w1", "sign_off", ""));
    expect(await screen.findByText(/Ravi on/)).toBeInTheDocument();
  });

  it("shows the server's refusal", async () => {
    api.submit.mockRejectedValue(new Error("Choose a reviewer before submitting"));
    render(<WorkpapersPage />);
    fireEvent.click(await screen.findByText("Revenue recognition FY26"));
    fireEvent.click(await screen.findByRole("button", { name: /Submit for review/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a reviewer before submitting");
  });
});
