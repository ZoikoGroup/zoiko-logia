"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, GraduationCap, Loader2, XCircle } from "lucide-react";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { createCPDEntry, getAuthToken } from "@/lib/api";
import {
  checkPracticeAnswer,
  drawPracticeQuestions,
  listPracticeBanks,
  type PracticeBank,
  type PracticeQuestion,
  type PracticeResult,
} from "@/lib/learning-practice-api";

const QUIZ_LENGTH = 5;

/** A short quiz from Kriton's question banks. A finished quiz is logged as
 * CPD with the time actually spent and the score, then onLogged() runs. */
export function PracticeQuiz({ onLogged }: { onLogged: () => void }) {
  const [banks, setBanks] = useState<PracticeBank[]>([]);
  const [bankId, setBankId] = useState("");
  const [questions, setQuestions] = useState<PracticeQuestion[]>([]);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<PracticeResult | null>(null);
  const [score, setScore] = useState(0);
  const [finished, setFinished] = useState(false);
  const [logged, setLogged] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const startedAt = useRef(0);

  useEffect(() => {
    listPracticeBanks()
      .then((list) => {
        setBanks(list);
        setBankId(list[0]?.id ?? "");
      })
      .catch(() => setError("Could not load practice questions."));
  }, []);

  const bank = banks.find((b) => b.id === bankId);
  const current = questions[index];

  async function start() {
    setBusy(true);
    setError("");
    try {
      setQuestions(await drawPracticeQuestions(bankId, QUIZ_LENGTH));
      setIndex(0);
      setScore(0);
      setAnswer("");
      setResult(null);
      setFinished(false);
      setLogged("");
      startedAt.current = Date.now();
    } catch (err) {
      setError((err instanceof Error && err.message) || "Could not start the quiz.");
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    if (!current || !answer.trim()) return;
    setBusy(true);
    setError("");
    try {
      const marked = await checkPracticeAnswer(bankId, current.id, answer);
      setResult(marked);
      if (marked.correct) setScore((s) => s + 1);
    } catch (err) {
      setError((err instanceof Error && err.message) || "Could not check the answer.");
    } finally {
      setBusy(false);
    }
  }

  async function next() {
    if (index + 1 < questions.length) {
      setIndex(index + 1);
      setAnswer("");
      setResult(null);
      return;
    }
    setFinished(true);
    // Real time spent, rounded up to a whole minute (CPD allows 1-600).
    const minutes = Math.min(600, Math.max(1, Math.ceil((Date.now() - startedAt.current) / 60000)));
    try {
      // The score is in the topic, which is what the CPD list shows.
      await createCPDEntry(getAuthToken(), {
        topic: `Practice quiz: ${bank?.title ?? bankId} (${score}/${questions.length})`,
        minutes,
      });
      setLogged(`Logged ${minutes} min to CPD.`);
      onLogged();
    } catch {
      setLogged("The quiz is finished, but it could not be logged to CPD.");
    }
  }

  return (
    <div className={`${PANEL_CLASS} mb-4`}>
      <PanelHeader icon={GraduationCap} tone="info" title="Practice quiz" subtitle={bank ? `${bank.questionCount} ${bank.title} questions` : undefined} />
      {error && <p className="mb-2 text-xs text-bad" role="alert">{error}</p>}

      {!questions.length || finished ? (
        <div className="space-y-3">
          {finished && (
            <div className="rounded-xl border border-line bg-soft p-3 text-sm text-ink">
              You scored <strong>{score} / {questions.length}</strong>. {logged}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs font-medium text-muted" htmlFor="practice-bank">Topic</label>
            <select
              id="practice-bank"
              value={bankId}
              onChange={(e) => setBankId(e.target.value)}
              className="rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none"
            >
              {banks.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
            </select>
            <button
              onClick={() => void start()}
              disabled={busy || !bankId}
              className="flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white hover:bg-brand-2 disabled:opacity-60"
            >
              {busy && <Loader2 size={12} className="animate-spin" />} {finished ? "Try another quiz" : `Start quiz (${QUIZ_LENGTH} questions)`}
            </button>
          </div>
          {bank && <p className="text-[11px] text-muted">Answers are checked against {bank.source}.</p>}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-muted">
            <span>Question {index + 1} of {questions.length}</span>
            <span>Score {score}</span>
          </div>
          <p className="text-sm font-semibold text-ink">{current.question}</p>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            disabled={!!result}
            rows={3}
            aria-label="Your answer"
            placeholder="Type your answer…"
            className="w-full resize-y rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          />
          {result && (
            <div className={`rounded-xl border p-3 text-sm ${result.correct ? "border-ok/30 bg-ok/5" : "border-bad/30 bg-bad/5"}`}>
              <p className={`flex items-center gap-1.5 font-semibold ${result.correct ? "text-ok" : "text-bad"}`}>
                {result.correct ? <CheckCircle2 size={15} /> : <XCircle size={15} />} {result.correct ? "Correct" : "Not quite"}
              </p>
              <p className="mt-1 text-xs text-ink">
                Key facts: {[...result.expected, ...(result.acceptedAlternatives.length ? [`one of: ${result.acceptedAlternatives.join(" / ")}`] : [])].join(" · ")}
              </p>
              <p className="mt-1 text-[11px] text-muted">Source: {result.source}</p>
            </div>
          )}
          <div className="flex gap-2">
            {!result ? (
              <button
                onClick={() => void check()}
                disabled={busy || !answer.trim()}
                className="rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white hover:bg-brand-2 disabled:opacity-60"
              >
                {busy ? "Checking…" : "Check answer"}
              </button>
            ) : (
              <button onClick={() => void next()} className="rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white hover:bg-brand-2">
                {index + 1 < questions.length ? "Next question" : "Finish quiz"}
              </button>
            )}
            <Pill>{current.category.replace(/_/g, " ")}</Pill>
          </div>
        </div>
      )}
    </div>
  );
}
