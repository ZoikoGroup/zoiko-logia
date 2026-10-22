import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({
  ask: vi.fn(), createCPD: vi.fn(), summary: vi.fn(), entries: vi.fn(), pathways: vi.fn(), topics: vi.fn(), deleteCPD: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  askKriton: api.ask, createCPDEntry: api.createCPD, getAuthToken: () => "token", getCPDSummary: api.summary,
  listCPDEntries: api.entries, listSyllabusPathways: api.pathways, listTopicMapNodes: api.topics,
  ApiError: class ApiError extends Error {},
}));
vi.mock("@/lib/learning-practice-api", () => ({ deleteCPDEntry: api.deleteCPD }));
vi.mock("@/components/learning/PracticeQuiz", () => ({ PracticeQuiz: () => <div>quiz</div> }));
vi.mock("@/components/AnswerRenderer", () => ({ AnswerRenderer: ({ text }: { text: string }) => <div data-testid="answer">{text}</div> }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
import LearningPracticePage from "@/app/learning-practice/page";

const pathways = [
  { id: "p1", body: "ACCA", qualification: "Financial Reporting", module: "Revenue Recognition", topic: "Deferred Revenue", learning_outcome: "Apply IFRS 15" },
  { id: "p2", body: "AICPA", qualification: "FAR", module: "Accruals", topic: "Accrued Expenses", learning_outcome: "Record accruals" },
];
const topics = [
  { id: "n1", topic: "Deferred Revenue", prerequisites: "Accruals, Revenue Recognition", standards_summary: "IFRS 15" },
  { id: "n2", topic: "Accruals", prerequisites: "", standards_summary: "IAS 1" },
];
const entries = [
  { id: "c1", topic: "Deferred Revenue", minutes: 90, note: "", logged_at: "2026-10-01T10:00:00Z" },
  { id: "c2", topic: "Practice quiz: UK VAT (4/5)", minutes: 30, note: "", logged_at: "2026-09-15T10:00:00Z" },
];

beforeEach(() => {
  api.pathways.mockReset().mockResolvedValue(pathways);
  api.topics.mockReset().mockResolvedValue(topics);
  api.entries.mockReset().mockResolvedValue(entries);
  api.summary.mockReset().mockResolvedValue({ total_minutes: 120, total_hours: 2, entries_count: 2 });
  api.ask.mockReset().mockResolvedValue({
    outcome: "ANSWERED", safety: { risk_level: "LOW", refusal_text: null },
    answer: { text: "## Deferred revenue\n\nIt is a liability.", citations: [
      { ref_id: "REF-1", source_id: "a", title: "IFRS 15", url: "https://www.ifrs.org/ifrs-15" },
      { ref_id: "REF-2", source_id: "a", title: "IFRS 15", url: "https://www.ifrs.org/ifrs-15" },
    ] },
  });
  api.deleteCPD.mockReset().mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  Element.prototype.scrollIntoView = vi.fn();
});

describe("Learning & Practice", () => {
  it("asks with the chosen jurisdiction and shows a formatted answer with each source once", async () => {
    render(<LearningPracticePage />);
    fireEvent.click(screen.getByRole("button", { name: "My Learning" }));
    fireEvent.change(await screen.findByLabelText("Jurisdiction"), { target: { value: "UK" } });
    fireEvent.change(document.getElementById("learning-ask-input")!, { target: { value: "What is deferred revenue?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(api.ask).toHaveBeenCalledWith("token", { query: "What is deferred revenue?", mode: "Learning", jurisdiction: "UK" }));
    expect(await screen.findByTestId("answer")).toHaveTextContent("It is a liability.");
    expect(screen.getAllByRole("link", { name: /IFRS 15/ })).toHaveLength(1);
    expect(screen.queryByText("Framework: US GAAP")).not.toBeInTheDocument();
  });

  it("shows pathway progress from CPD and fills the Ask box from a topic", async () => {
    render(<LearningPracticePage />);
    fireEvent.click(screen.getByRole("button", { name: "My Learning" }));
    expect(await screen.findByText("1 of 2 studied")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Pathway progress" })).toHaveAttribute("aria-valuenow", "1");
    fireEvent.click(screen.getAllByRole("button", { name: /Ask Kriton/ })[1]);
    expect(screen.getByDisplayValue(/Explain Accrued Expenses for AICPA FAR/)).toBeInTheDocument();
    expect(api.ask).not.toHaveBeenCalled();
  });

  it("links a prerequisite to its topic, or to Ask Kriton when there is none", async () => {
    render(<LearningPracticePage />);
    fireEvent.click(screen.getByRole("button", { name: "My Learning" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accruals" }));
    expect(document.getElementById("topic-n2")?.className).toContain("ring-1");
    fireEvent.click(screen.getByRole("button", { name: "Revenue Recognition" }));
    expect(screen.getByDisplayValue("Explain Revenue Recognition.")).toBeInTheDocument();
  });

  it("totals CPD by topic and month, and deletes an entry", async () => {
    render(<LearningPracticePage />);
    fireEvent.click(screen.getByRole("button", { name: "Progress" }));
    await screen.findByText("By topic");
    expect(within(screen.getByText("By topic").parentElement!).getByText("1.5h")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete CPD entry Deferred Revenue" }));
    await waitFor(() => expect(api.deleteCPD).toHaveBeenCalledWith("c1"));
    expect(screen.getByRole("button", { name: /Download CPD log/ })).toBeInTheDocument();
  });
});
