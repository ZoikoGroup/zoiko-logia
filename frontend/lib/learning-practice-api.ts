import { getAuthToken } from "@/lib/api";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";
const PRACTICE = `${API_URL}/learning/practice`;

// Practice quizzes (backend/app/domains/learning_cpd/practice.py).
export type PracticeBank = { id: string; title: string; questionCount: number; source: string };
export type PracticeQuestion = { id: string; question: string; category: string };
export type PracticeResult = {
  correct: boolean;
  expected: string[];
  acceptedAlternatives: string[];
  missing: string[];
  source: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PRACTICE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getAuthToken()}`,
      ...init?.headers,
      ...impersonationHeaders(),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.json();
}

export const listPracticeBanks = () => request<PracticeBank[]>("/banks");

export const drawPracticeQuestions = (bankId: string, count = 5) =>
  request<PracticeQuestion[]>(`/${encodeURIComponent(bankId)}/questions?count=${count}`);

/** Remove one of the user's own CPD entries (audited by the backend). */
export async function deleteCPDEntry(entryId: string): Promise<void> {
  const res = await fetch(`${API_URL}/learning/cpd/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${getAuthToken()}`, ...impersonationHeaders() },
  });
  if (!res.ok) throw new Error(`Could not delete this CPD entry (${res.status})`);
}

export const checkPracticeAnswer = (bankId: string, questionId: string, answer: string) =>
  request<PracticeResult>(`/${encodeURIComponent(bankId)}/check`, {
    method: "POST",
    body: JSON.stringify({ question_id: questionId, answer }),
  });
