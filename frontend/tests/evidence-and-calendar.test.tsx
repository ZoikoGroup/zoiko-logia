import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ answers: vi.fn(), drafts: vi.fn(), pack: vi.fn(), calendar: vi.fn() }));
vi.mock("@/lib/api", () => ({ getAuthToken: () => "token", listSavedAnswers: api.answers, listDrafts: api.drafts }));
vi.mock("@/lib/accounting-workflows-api", () => ({ downloadEvidencePack: api.pack, getComplianceCalendar: api.calendar }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
import EvidencePacksPage from "@/app/evidence-packs/page";
import ComplianceCalendarPage from "@/app/compliance-calendar/page";

const deadline = (over: object) => ({
  id: "in-gstr3b:2026-10-20", rule: "in-gstr3b", jurisdiction: "India", title: "GSTR-3B return and GST payment", category: "GST",
  dueDate: "2026-10-20", daysLeft: 6, assumes: "Monthly filers.", source: "https://www.gst.gov.in", weekendNote: null, ...over,
});

beforeEach(() => {
  api.answers.mockReset().mockResolvedValue([{ id: "sa1", query_text: "What is the UK VAT threshold?", risk_level: "LOW", created_at: "2026-10-13T10:00:00Z" }]);
  api.drafts.mockReset().mockResolvedValue([{ id: "d1", title: "VAT memo", status: "Final", saved_answer_id: "sa1", updated_at: "2026-10-14T10:00:00Z" }]);
  api.pack.mockReset().mockResolvedValue(undefined);
  api.calendar.mockReset().mockResolvedValue({
    from: "2026-10-14", to: "2027-01-12", jurisdictions: ["India", "UK", "US"], disclaimer: "General statutory deadlines.",
    deadlines: [deadline({}), deadline({ id: "us-1040es:2027-01-15", rule: "us-1040es", jurisdiction: "US", title: "Estimated tax payment",
      category: "Income tax", dueDate: "2027-01-09", daysLeft: 87, source: "https://www.irs.gov", weekendNote: "The IRS treats a deadline on a weekend as met on the next business day." })],
  });
});

describe("Evidence Packs", () => {
  it("lists saved answers and drafts, newest first, and downloads a pack", async () => {
    render(<EvidencePacksPage />);
    const buttons = await screen.findAllByRole("button", { name: /Download evidence pack for/ });
    expect(buttons[0]).toHaveAccessibleName("Download evidence pack for VAT memo");
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(api.pack).toHaveBeenCalledWith("saved-answer", "sa1"));
    expect(await screen.findByText(/downloaded/)).toBeInTheDocument();
  });

  it("shows a failed download", async () => {
    api.pack.mockRejectedValue(new Error("Saved answer not found"));
    render(<EvidencePacksPage />);
    fireEvent.click((await screen.findAllByRole("button", { name: /Download evidence pack for/ }))[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Saved answer not found");
  });
});

describe("Compliance Calendar", () => {
  it("groups real deadlines by month with sources, urgency and weekend notes", async () => {
    render(<ComplianceCalendarPage />);
    expect(await screen.findByText("GSTR-3B return and GST payment")).toBeInTheDocument();
    expect(screen.getByText("October 2026")).toBeInTheDocument();
    expect(screen.getByText("6 days left")).toBeInTheDocument();
    expect(screen.getByText(/1 within 7 days/)).toBeInTheDocument();
    expect(screen.getByText(/Falls on a weekend/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Official source/ })[0]).toHaveAttribute("href", "https://www.gst.gov.in");
    expect(api.calendar).toHaveBeenCalledWith(90, "", expect.anything());
  });

  it("filters by country and range", async () => {
    render(<ComplianceCalendarPage />);
    fireEvent.click(await screen.findByRole("button", { name: "UK" }));
    await waitFor(() => expect(api.calendar).toHaveBeenLastCalledWith(90, "UK", expect.anything()));
    fireEvent.click(screen.getByRole("button", { name: "Next 12 months" }));
    await waitFor(() => expect(api.calendar).toHaveBeenLastCalledWith(365, "UK", expect.anything()));
  });
});
