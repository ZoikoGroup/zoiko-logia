import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ list: vi.fn(), stats: vi.fn(), update: vi.fn(), close: vi.fn() }));
vi.mock("@/lib/incident-api", () => ({
  IncidentApiError: class IncidentApiError extends Error {
    constructor(public status: number, message: string) { super(message); }
  },
  getIncidents: api.list, getIncidentStats: api.stats, updateIncident: api.update, closeIncident: api.close,
}));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
import { IncidentApiError } from "@/lib/incident-api";
import IncidentResponsePage from "@/app/incident-response/page";

const incident = {
  id: "inc-1", tenant_id: "t1", title: "PII in an upload", severity: "High", containment_status: "OPEN",
  source: "PII_LEAK", query_id: null, restricted_sub_class: null, assigned_to: null, timeline: [],
  opened_at: "2026-10-08T10:00:00Z", resolved_at: null, resolution_note: null,
};
const stats = { total: 1, open: 1, contained: 0, resolved: 0, critical: 0, high: 1 };

beforeEach(() => {
  api.list.mockReset().mockResolvedValue([incident]);
  api.stats.mockReset().mockResolvedValue(stats);
  api.update.mockReset().mockResolvedValue({ ...incident, containment_status: "CONTAINED" });
  api.close.mockReset();
});

describe("incident response", () => {
  it("sends the action without a made-up actor name", async () => {
    render(<IncidentResponsePage />);
    fireEvent.click(await screen.findByText("PII in an upload"));
    fireEvent.change(screen.getByPlaceholderText(/investigation or resolution note/), { target: { value: "Isolated the upload." } });
    fireEvent.click(screen.getByRole("button", { name: "Mark Contained" }));
    await waitFor(() => expect(api.update).toHaveBeenCalledWith("inc-1", "CONTAIN", "Isolated the upload."));
  });

  it("shows a failed action instead of pretending it worked", async () => {
    api.update.mockRejectedValue(new IncidentApiError(403, "forbidden"));
    render(<IncidentResponsePage />);
    fireEvent.click(await screen.findByText("PII in an upload"));
    fireEvent.click(screen.getByRole("button", { name: "Mark Contained" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your role does not have permission for this.");
    expect(screen.getByRole("button", { name: "Mark Contained" })).toBeInTheDocument();   // panel stays open
  });

  it("reports a load failure rather than an empty list", async () => {
    api.list.mockRejectedValue(new IncidentApiError(403, "forbidden"));
    render(<IncidentResponsePage />);
    expect(await screen.findByText("Your role does not have permission for this.")).toBeInTheDocument();
    expect(screen.getByText("Incidents could not be shown.")).toBeInTheDocument();
    expect(screen.queryByText("No incidents found.")).not.toBeInTheDocument();
  });
});
