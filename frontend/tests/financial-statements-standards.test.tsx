import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ preview: vi.fn(), save: vi.fn(), list: vi.fn(), approve: vi.fn() }));
vi.mock("@/lib/financial-statements-api", () => ({
  previewResolution: api.preview, saveResolution: api.save, listResolutions: api.list, approveResolution: api.approve,
}));
import { StandardsPanel } from "@/components/financial-statements/StandardsPanel";

const RESULT = {
  state: "EVIDENCE_PENDING", selected_framework: null, size_class: "UNKNOWN",
  candidates: [{ framework: "FRS102", status: "PERMITTED", reason: "UK GAAP for UK companies.", sources: ["https://frc.example/frs102"] },
    { framework: "US_GAAP", status: "PROHIBITED", reason: "Not permitted for UK accounts.", sources: [] }],
  rules: [], statements: [], blockers: ["ELIGIBILITY_UNPROVEN"],
  reasons: { ELIGIBILITY_UNPROVEN: "FRS102_1A needs proven eligibility.", SIZE: "All three figures are needed." },
  permit_illustrative_draft: true, permit_statutory_claim: false, permitted_exports: ["WATERMARKED_ILLUSTRATIVE"],
  rule_pack: { id: "UK_IFRS_USGAAP_2026_TEST", status: "UNREVIEWED_TEST_PACK", checked: "2026-10-24", digest: "sha256:abcdef123456", capabilities: {} },
};
const SAVED = { id: "r1", revision: 1, state: "REVIEW_REQUIRED", entity_key: "k", facts_hash: "h", rule_pack_digest: "d",
  trial_balance_id: null, prepared_by: "prep", approved_by: null, approved_at: null, created_at: null,
  facts: { entity_name: "Northbridge Trading Ltd" },
  result: { ...RESULT, state: "REVIEW_REQUIRED", selected_framework: "FRS102_1A", blockers: [] } };

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([SAVED]);
  api.preview.mockResolvedValue(RESULT);
});

describe("Framework & rules panel (Document 03)", () => {
  it("shows candidates, blockers and the unreviewed rule pack", async () => {
    render(<StandardsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /check applicability/i }));
    expect(await screen.findByText(/1 blocker/i)).toBeTruthy();
    expect(screen.getByText(/FRS102_1A needs proven eligibility/)).toBeTruthy();
    expect(screen.getByText("PROHIBITED")).toBeTruthy();
    expect(screen.getByText(/unreviewed test pack/i)).toBeTruthy();
    expect(screen.getByText("Not permitted")).toBeTruthy();
    expect(api.preview.mock.calls[0][0]).toMatchObject({ incorporation_jurisdiction: "GB-ENG", requested_claim: "illustrative" });
  });

  it("lists saved resolutions and sends approval", async () => {
    api.approve.mockResolvedValue({ ...SAVED, state: "FROZEN" });
    render(<StandardsPanel />);
    expect(await screen.findByText("Northbridge Trading Ltd")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.approve).toHaveBeenCalledWith("r1"));
  });
});
