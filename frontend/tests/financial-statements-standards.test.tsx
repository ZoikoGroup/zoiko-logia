import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  preview: vi.fn(), save: vi.fn(), list: vi.fn(), approve: vi.fn(), review: vi.fn(), judge: vi.fn(),
  reject: vi.fn(), revoke: vi.fn(), release: vi.fn(),
}));
vi.mock("@/lib/financial-statements-api", () => ({
  previewResolution: api.preview, saveResolution: api.save, listResolutions: api.list, approveResolution: api.approve,
  requestReview: api.review, recordJudgment: api.judge, rejectResolution: api.reject, revokeResolution: api.revoke,
  releaseCheck: api.release,
}));
import { StandardsPanel } from "@/components/financial-statements/StandardsPanel";

const RESULT = {
  state: "EVIDENCE_PENDING", selected_framework: null, framework_edition: null, size_class: "UNKNOWN",
  eligibility: { result: "UNKNOWN", band: "thresholds for years beginning before 6 April 2025", exclusions: [],
    tests: [{ size: "micro", current: null, prior: null,
      current_criteria: [{ criterion: "turnover", value: "1850000", limit: "632000", within: false }],
      prior_criteria: [{ criterion: "turnover", value: null, limit: "632000", within: null }] }] },
  candidates: [{ framework: "FRS102", status: "PERMITTED", reason: "UK GAAP for UK companies.", sources: ["S1"] },
    { framework: "US_GAAP", status: "PROHIBITED", reason: "Not permitted for UK accounts.", sources: [] }],
  rules: [{ rule_id: "FRS102.PERIODIC_REVIEW_2024", outcome: "NOT_YET_EFFECTIVE", effective: "periods beginning on or after 2026-01-01",
    source: "S1", adoption: "NOT_YET_EFFECTIVE", endorsement: "" }],
  statements: [], blockers: ["ELIGIBILITY_UNPROVEN"],
  reasons: { ELIGIBILITY_UNPROVEN: "FRS102_1A needs proven eligibility.", SIZE: "All three figures are needed." },
  findings: [{ code: "ELIGIBILITY_UNPROVEN", severity: "CRITICAL", owner: "Preparer", reason: "FRS102_1A needs proven eligibility.",
    action: "Provide two years of figures." }],
  pending_judgments: [], judgments: {},
  gates: [{ gate: "G2", title: "Eligibility", passed: false, detail: "Size and exemption tests complete." }],
  outputs: [{ type: "ILLUSTRATIVE_DRAFT", allowed: true, gate: "Always watermarked." },
    { type: "STATUTORY_READY", allowed: false, gate: "Zero blockers." }],
  explanation: ["No framework is selected yet; the permitted candidates are listed."],
  citations: { S1: { publisher: "FRC", title: "FRS 102 standard editions", url: "https://frc.example/frs102", checked: "2026-10-24", snapshot: null } },
  permit_illustrative_draft: true, permit_statutory_claim: false, permitted_exports: ["WATERMARKED_ILLUSTRATIVE"], as_of: "2026-10-26",
  rule_pack: { id: "UK_IFRS_USGAAP_2026_TEST", version: "2026.10.24", status: "UNREVIEWED_TEST_PACK", checked: "2026-10-24",
    valid_until: "2027-04-22", owner: "Unassigned", digest: "sha256:abcdef123456", capabilities: {} },
};
const SAVED = { id: "r1", revision: 1, state: "REVIEW_REQUIRED", entity_key: "k", facts_hash: "h", rule_pack_digest: "d",
  trial_balance_id: null, prepared_by: "prep", approved_by: null, approved_at: null, created_at: null,
  pack_is_current: true, approval_valid: false, judgments: {},
  history: [{ action: "context_captured", actor_id: "prep", at: "2026-10-26T10:00:00Z", state: "REVIEW_REQUIRED", detail: {} }],
  facts: { entity_name: "Northbridge Trading Ltd" },
  result: { ...RESULT, state: "REVIEW_REQUIRED", selected_framework: "FRS102_1A", blockers: [], findings: [],
    pending_judgments: [{ key: "POLICY:lease_term", question: "Accounting-policy judgment: lease term.", sources: [], decided: false }] } };

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([SAVED]);
  api.preview.mockResolvedValue(RESULT);
});

describe("Framework & rules panel (Document 03)", () => {
  it("shows readiness with owner and action, candidates, the size calculation and the unreviewed pack", async () => {
    render(<StandardsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /check applicability/i }));
    expect(await screen.findByText(/1 blocker/i)).toBeTruthy();
    expect(screen.getByText(/owner: Preparer/)).toBeTruthy();
    expect(screen.getByText(/Action: Provide two years/)).toBeTruthy();
    expect(screen.getByText("PROHIBITED")).toBeTruthy();
    expect(screen.getByText("632000")).toBeTruthy();
    expect(screen.getByText(/G2 Eligibility/)).toBeTruthy();
    expect(screen.getByText(/unreviewed test pack/i)).toBeTruthy();
    expect(screen.getByText("Not permitted")).toBeTruthy();
    expect(api.preview.mock.calls[0][0]).toMatchObject({ incorporation_jurisdiction: "GB-ENG", requested_claim: "illustrative" });
  });

  it("opens a saved resolution with history, records a judgment and approves", async () => {
    api.judge.mockResolvedValue(SAVED);
    api.approve.mockResolvedValue({ ...SAVED, state: "FROZEN" });
    render(<StandardsPanel />);
    fireEvent.click(await screen.findByText("Northbridge Trading Ltd"));
    expect(screen.getByText("context captured")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Choice for POLICY:lease_term"), { target: { value: "5 years" } });
    fireEvent.change(screen.getByLabelText("Reason for POLICY:lease_term"), { target: { value: "Break clause unlikely" } });
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() => expect(api.judge).toHaveBeenCalledWith("r1", { key: "POLICY:lease_term", choice: "5 years", reason: "Break clause unlikely" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.approve).toHaveBeenCalledWith("r1"));
  });

  it("shows why a statutory release is blocked", async () => {
    api.release.mockResolvedValue({ resolution_id: "r1", revision: 1, statutory_release_allowed: false, illustrative_allowed: true,
      reasons: ["The resolution is review required, not approved and frozen."], rule_pack_digest: "d", framework_edition: null });
    render(<StandardsPanel />);
    fireEvent.click(await screen.findByText("Northbridge Trading Ltd"));
    fireEvent.click(screen.getByRole("button", { name: "Release check" }));
    expect(await screen.findByText("Statutory release blocked")).toBeTruthy();
  });
});
