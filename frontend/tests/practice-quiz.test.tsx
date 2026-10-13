import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ banks: vi.fn(), draw: vi.fn(), check: vi.fn(), cpd: vi.fn() }));
vi.mock("@/lib/learning-practice-api", () => ({ listPracticeBanks: api.banks, drawPracticeQuestions: api.draw, checkPracticeAnswer: api.check }));
vi.mock("@/lib/api", () => ({ getAuthToken: () => "token", createCPDEntry: api.cpd }));
import { PracticeQuiz } from "@/components/learning/PracticeQuiz";

const questions = [
  { id: "q1", question: "What is the UK VAT registration threshold?", category: "rates_thresholds" },
  { id: "q2", question: "How long do I have to register?", category: "procedure" },
];

beforeEach(() => {
  api.banks.mockReset().mockResolvedValue([{ id: "uk-vat", title: "UK VAT", questionCount: 32, source: "HMRC guidance on GOV.UK" }]);
  api.draw.mockReset().mockResolvedValue(questions);
  api.check.mockReset()
    .mockResolvedValueOnce({ correct: true, expected: ["90,000"], acceptedAlternatives: [], missing: [], source: "HMRC guidance on GOV.UK" })
    .mockResolvedValueOnce({ correct: false, expected: ["30 days"], acceptedAlternatives: [], missing: ["30 days"], source: "HMRC guidance on GOV.UK" });
  api.cpd.mockReset().mockResolvedValue({});
});

async function answer(text: string) {
  fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Check answer" }));
}

describe("practice quiz", () => {
  it("marks answers, shows the key facts and logs the finished quiz to CPD", async () => {
    const onLogged = vi.fn();
    render(<PracticeQuiz onLogged={onLogged} />);
    fireEvent.click(await screen.findByRole("button", { name: /Start quiz/ }));

    expect(await screen.findByText(questions[0].question)).toBeInTheDocument();
    await answer("£90,000");
    expect(await screen.findByText("Correct")).toBeInTheDocument();
    expect(api.check).toHaveBeenCalledWith("uk-vat", "q1", "£90,000");
    fireEvent.click(screen.getByRole("button", { name: "Next question" }));

    await answer("14 days");
    expect(await screen.findByText("Not quite")).toBeInTheDocument();
    expect(screen.getByText(/Key facts: 30 days/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Finish quiz" }));

    expect(await screen.findByText(/You scored/)).toHaveTextContent("You scored 1 / 2");
    await waitFor(() => expect(api.cpd).toHaveBeenCalledWith("token", { topic: "Practice quiz: UK VAT (1/2)", minutes: 1 }));
    expect(onLogged).toHaveBeenCalled();
  });

  it("does not check an empty answer", async () => {
    render(<PracticeQuiz onLogged={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Start quiz/ }));
    await screen.findByText(questions[0].question);
    expect(screen.getByRole("button", { name: "Check answer" })).toBeDisabled();
  });

  it("reports when questions cannot be loaded", async () => {
    api.banks.mockRejectedValue(new Error("down"));
    render(<PracticeQuiz onLogged={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load practice questions.");
  });
});
