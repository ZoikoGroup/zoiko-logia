"use client";

import { useState } from "react";
import { CheckCircle2, Loader2, ThumbsDown, ThumbsUp } from "lucide-react";
import { ApiError, getAuthToken, submitAnswerFeedback, type FeedbackReason } from "@/lib/api";

// What was wrong, in the reviewer's terms: each reason maps to a failure
// class the evaluation reports (wrong figure, wrong source, outdated, …).
const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "wrong_answer", label: "Wrong answer" },
  { value: "wrong_calculation", label: "Wrong calculation" },
  { value: "outdated", label: "Outdated" },
  { value: "wrong_source", label: "Wrong source" },
  { value: "wrong_jurisdiction", label: "Wrong country" },
  { value: "missing_evidence", label: "Missing evidence" },
  { value: "missing_citation", label: "Missing citation" },
  { value: "poor_explanation", label: "Unclear" },
  { value: "other", label: "Other" },
];

type State = "idle" | "choosing" | "sending" | "sent-up" | "sent-down" | "error";

/** Thumbs up / down on an answer. A thumbs-down, with its reasons, opens a
 * review case so a reviewer can correct the answer — and the correction
 * becomes an evaluation case. */
export function AnswerFeedback({
  queryId,
  question,
  answerText,
}: {
  queryId: string;
  question: string;
  answerText: string;
}) {
  const [state, setState] = useState<State>("idle");
  const [reasons, setReasons] = useState<FeedbackReason[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");

  async function send(rating: "up" | "down") {
    const token = getAuthToken();
    if (!token) {
      setError("Sign in to rate answers.");
      setState("error");
      return;
    }
    setState("sending");
    try {
      await submitAnswerFeedback(token, {
        query_id: queryId,
        rating,
        reasons: rating === "down" ? reasons : [],
        comment: rating === "down" ? comment.trim() : "",
        question,
        answer_text: answerText,
      });
      setState(rating === "up" ? "sent-up" : "sent-down");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send feedback.");
      setState("error");
    }
  }

  if (state === "sent-up" || state === "sent-down") {
    return (
      <span className="inline-flex h-8 items-center gap-1.5 px-2 text-[11px] font-semibold text-ok" role="status">
        <CheckCircle2 size={15} />
        {state === "sent-up" ? "Thanks for the feedback" : "Sent to a reviewer — thank you"}
      </span>
    );
  }

  const toggle = (value: FeedbackReason) =>
    setReasons((current) => (current.includes(value) ? current.filter((r) => r !== value) : [...current, value]));

  return (
    <>
      <button
        type="button"
        onClick={() => send("up")}
        disabled={state === "sending"}
        title="This answer was helpful"
        aria-label="This answer was helpful"
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted transition hover:bg-soft hover:text-ink disabled:opacity-50"
      >
        <ThumbsUp size={16} />
      </button>
      <button
        type="button"
        onClick={() => setState(state === "choosing" ? "idle" : "choosing")}
        disabled={state === "sending"}
        title="Report a problem with this answer"
        aria-label="Report a problem with this answer"
        aria-expanded={state === "choosing"}
        className={`inline-flex h-8 w-8 items-center justify-center rounded-lg transition disabled:opacity-50 ${
          state === "choosing" ? "bg-soft text-ink" : "text-muted hover:bg-soft hover:text-ink"
        }`}
      >
        <ThumbsDown size={16} />
      </button>
      {state === "error" && <span className="px-1 text-[11px] font-semibold text-bad">{error}</span>}
      {(state === "choosing" || state === "sending") && (
        <div className="mt-2 basis-full rounded-xl border border-line bg-panel p-3">
          <p className="mb-2 text-xs font-semibold text-ink">What was wrong?</p>
          <div className="flex flex-wrap gap-1.5">
            {REASONS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => toggle(value)}
                aria-pressed={reasons.includes(value)}
                className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition ${
                  reasons.includes(value)
                    ? "border-brand bg-brand/10 text-brand"
                    : "border-line text-muted hover:border-ink/30 hover:text-ink"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            rows={2}
            placeholder="Optional: what should it have said? (e.g. the correct rate and its source)"
            className="mt-2 w-full resize-y rounded-lg border border-line bg-panel px-2.5 py-2 text-xs text-ink placeholder:text-muted focus:border-brand focus:outline-none"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setState("idle")}
              className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-muted hover:bg-soft hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => send("down")}
              disabled={state === "sending" || (reasons.length === 0 && !comment.trim())}
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-brand/90 disabled:opacity-50"
            >
              {state === "sending" && <Loader2 size={13} className="animate-spin" />}
              Send to reviewer
            </button>
          </div>
        </div>
      )}
    </>
  );
}
