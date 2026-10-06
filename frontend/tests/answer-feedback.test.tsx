import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const submitAnswerFeedback = vi.fn();
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  getAuthToken: () => "token",
  submitAnswerFeedback: (...args: unknown[]) => submitAnswerFeedback(...args),
}));

import { AnswerFeedback } from "@/components/ask-kriton/AnswerFeedback";

const props = { queryId: "q-1", question: "What is the UK VAT threshold?", answerText: "£85,000." };

describe("answer feedback", () => {
  beforeEach(() => {
    submitAnswerFeedback.mockReset().mockResolvedValue({ id: "f1", rating: "down", review_case_id: "rc1" });
  });

  it("sends a thumbs-up straight away", async () => {
    render(<AnswerFeedback {...props} />);
    fireEvent.click(screen.getByLabelText("This answer was helpful"));
    await screen.findByText("Thanks for the feedback");
    expect(submitAnswerFeedback).toHaveBeenCalledWith("token", expect.objectContaining({
      query_id: "q-1", rating: "up", reasons: [], comment: "",
    }));
  });

  it("asks what was wrong before sending a thumbs-down to a reviewer", async () => {
    render(<AnswerFeedback {...props} />);
    fireEvent.click(screen.getByLabelText("Report a problem with this answer"));
    const send = screen.getByRole("button", { name: /send to reviewer/i });
    expect(send).toBeDisabled(); // nothing chosen yet

    fireEvent.click(screen.getByRole("button", { name: "Outdated" }));
    fireEvent.change(screen.getByPlaceholderText(/what should it have said/i), {
      target: { value: "The threshold is £90,000 since April 2024." },
    });
    expect(send).toBeEnabled();
    fireEvent.click(send);

    await screen.findByText(/sent to a reviewer/i);
    expect(submitAnswerFeedback).toHaveBeenCalledWith("token", {
      query_id: "q-1",
      rating: "down",
      reasons: ["outdated"],
      comment: "The threshold is £90,000 since April 2024.",
      question: props.question,
      answer_text: props.answerText,
    });
  });

  it("shows the error when sending fails", async () => {
    submitAnswerFeedback.mockRejectedValue(new Error("network"));
    render(<AnswerFeedback {...props} />);
    fireEvent.click(screen.getByLabelText("This answer was helpful"));
    await waitFor(() => expect(screen.getByText("Could not send feedback.")).toBeInTheDocument());
  });
});
