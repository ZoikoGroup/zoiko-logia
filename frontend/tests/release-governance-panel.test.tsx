import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The WF-01 panel renders the server's verdict, gate states and ledger
// counts as given: NOT_RUN stays visible as NOT RUN, nothing is shown as
// passing that the server did not say passed, and actions follow the role.
const live = vi.hoisted(() => ({ byKey: {} as Record<string, unknown>, error: "" }));
const auth = vi.hoisted(() => ({ role: "CTO" }));
const api = vi.hoisted(() => ({ recordReleaseVerdict: vi.fn(), adjudicateQaObservation: vi.fn(), createQaRun: vi.fn() }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: (key: string) => ({ data: live.byKey[key] ?? null, error: live.error, loading: false, signedOut: false, reload: () => {} }),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: { id: "me", role: auth.role } }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/components/operations/ui", async (original) => ({
  ...(await original<typeof import("@/components/operations/ui")>()),
  useMutation: () => ({ busy: "", error: "", setError: () => {}, run: (_k: string, fn: (t: string) => Promise<unknown>) => fn("token").then(() => true) }),
}));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

import ReleaseGatesPage from "@/app/release-gates/page";
import { label, stateTone } from "@/components/governance/ReleaseGovernancePanel";

const gate = (state: string, reason: string) => ({ state, reason, evidence: {} });
const OVERVIEW = {
  verdict: { scope: "platform", verdict: "NO_GO", evidence_sha256: "a".repeat(64), gates: {
    authority: gate("BLOCKED", "1 unresolved identifier collision(s) (ZL-ENG-06)."),
    ownership: gate("NOT_RUN", "The gap allocation has not been adopted."),
    qa_pack: gate("BLOCKED", "The QA manifest is DRAFT_UNRATIFIED."),
    asbuilt: gate("NOT_RUN", "No as-built manifest has been recorded."),
    runtime_qa: gate("NOT_RUN", "No qualifying run."),
    signing: gate("BLOCKED", "No signing key is configured."),
  } },
  authority: { summary: { documents: 40, states: { EVIDENCE_UNAVAILABLE_IN_REPO: 31 }, unresolved_collisions: ["ZL-ENG-06"] } },
  ownership: { current: { status: "NOT_ADOPTED", proposed_sha256: "b".repeat(64) } },
  asbuilt: { manifest: null },
  qa: { pack_sha256: "c", cases: 72, planned_observations: 292, case_counts: { NOT_RUN: 72 },
        observation_status: { NOT_RUN: 292, EXECUTED: 0, BLOCKED: 0, FAILED_TO_EXECUTE: 0 },
        qualifying_runs: 0, p0_passed: 0, p0_total: 38, case_status: {} },
  adapter: { readiness: "MISSING", reason: "not configured" },
  fixtures: { target: null, fixtures: { F0: { status: "DRAFT_UNRATIFIED", signature: "NOT_RUN", specification: "NB-FIN-v1", derivations: [] } },
              files: [{ ref: "F0/NB-FIN-v1.csv", fixture_id: "F0", sha256: "d", intact: true, uploadable: true, used_by: ["A01"],
                        manifest_status: "DRAFT_UNRATIFIED", tenant_slot: "A", provision: "NOT_PROVISIONED", document_id: null }] },
  runs: [{ id: "run-1", environment: "local-dev", qualifying: false, adapter_readiness: "CONNECTED", started_by: "qa",
           pinned: {}, created_at: "2026-11-04T10:00:00Z" }],
};

beforeEach(() => {
  live.byKey = { "release-governance": OVERVIEW };
  live.error = "";
  Object.values(api).forEach((fn) => fn.mockReset().mockResolvedValue({}));
});

describe("Platform release governance panel", () => {
  it("shows NO-GO with every gate's own state and never a pass it was not given", () => {
    auth.role = "CTO";
    render(<ReleaseGatesPage />);
    expect(screen.getByTestId("verdict")).toHaveTextContent("NO-GO");
    expect(screen.getAllByText("NOT RUN").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("BLOCKED").length).toBe(3);
    expect(screen.queryByText("SATISFIED")).not.toBeInTheDocument();
    expect(screen.getByText("0 / 38")).toBeInTheDocument();                       // P0 passed
    expect(screen.getByText(/Verification is NOT RUN/)).toBeInTheDocument();
    expect(screen.getAllByText("DRAFT UNRATIFIED").length).toBeGreaterThan(0);
  });

  it("offers each role only its own actions", () => {
    auth.role = "CTO";
    const { unmount } = render(<ReleaseGatesPage />);
    expect(screen.getByRole("button", { name: "Record verdict" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Provision fixtures" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record verdict" }));
    expect(api.recordReleaseVerdict).toHaveBeenCalledWith("token");
    unmount();

    auth.role = "QA Automation";
    render(<ReleaseGatesPage />);
    expect(screen.getByRole("button", { name: "Provision fixtures" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record verdict" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("model"), { target: { value: "m" } });
    fireEvent.click(screen.getByRole("button", { name: "Start pinned run" }));
    expect(api.createQaRun).toHaveBeenCalledWith("token", { model: "m" });       // the server refuses it unpinned
  });

  it("lets Independent QA adjudicate only with an oracle and a reason, and flags mock answers", () => {
    auth.role = "Independent QA";
    live.byKey["qa-observations:run-1"] = [
      { id: "o1", case_id: "E05", repetition: 1, state: "EXECUTED", reason: "", output_excerpt: "[mock completion] text",
        trace: {}, automated_checks: { mock_completion: true }, adjudication: "NOT_ADJUDICATED" },
      { id: "o2", case_id: "A01", repetition: 1, state: "BLOCKED", reason: "fixture not provisioned", output_excerpt: "",
        trace: null, automated_checks: null, adjudication: "NOT_ADJUDICATED" },
    ];
    render(<ReleaseGatesPage />);
    const queue = screen.getByText("Adjudication queue").closest("section")!;
    expect(within(queue).getByText("Mock completion, not a model answer")).toBeInTheDocument();
    expect(within(queue).queryByText(/A01/)).not.toBeInTheDocument();             // BLOCKED cannot be adjudicated
    const pass = within(queue).getByRole("button", { name: "PASSED" });
    expect(pass).toBeDisabled();
    fireEvent.change(within(queue).getByLabelText("Oracle version"), { target: { value: "qbank-v1" } });
    fireEvent.change(within(queue).getByLabelText("Reason for E05 repetition 1"), { target: { value: "mock output" } });
    fireEvent.click(within(queue).getByRole("button", { name: "INCONCLUSIVE" }));
    expect(api.adjudicateQaObservation).toHaveBeenCalledWith("token", "o1", "INCONCLUSIVE", "qbank-v1", "mock output");
  });

  it("shows the server's refusal to an account outside the governance tenant", () => {
    auth.role = "CTO";
    live.byKey = {};
    live.error = "Platform release governance is limited to the governance tenant.";
    render(<ReleaseGatesPage />);
    expect(screen.getByText("Not available to this account")).toBeInTheDocument();
    expect(screen.getByText(/limited to the governance tenant/)).toBeInTheDocument();
  });

  it("keeps the tenant release register for tenant roles", () => {
    auth.role = "Admin";
    live.byKey = {};
    render(<ReleaseGatesPage />);
    expect(screen.queryByText("Platform release verdict")).not.toBeInTheDocument();
    expect(screen.getByText("Release Gates", { selector: "h1, h2, p, span" })).toBeInTheDocument();
  });

  it("labels unknown states as not run and never as passing", () => {
    expect(label(undefined)).toBe("NOT RUN");
    expect(label("NOT_RUN")).toBe("NOT RUN");
    expect(stateTone("NOT_RUN")).toBe("neutral");
    expect(stateTone("SOMETHING_NEW")).toBe("neutral");
    expect(stateTone("UNSIGNED_NO_KEY")).not.toBe("ok");
  });
});
