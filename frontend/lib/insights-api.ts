import { getAuthToken } from "@/lib/api";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010/api/v1";

// Shape of GET /api/v1/kriton-workspace/insights (backend/app/domains/kriton_workspace/insights.py).
// A section is null when the backend could not read it in time.
export type Count = { label: string; count: number };
export type Insights = {
  windowDays: number;
  since: string;
  generatedAt: string;
  totalQuestions: number | null;
  questionsPerDay: { date: string; count: number }[] | null;
  outcomes: Count[] | null;
  routes: Count[] | null;
  riskLevels: Count[] | null;
  latency: { averageMs: number; maxMs: number; measured: number } | null;
  answers: { answersSampled: number; topics: Count[]; sourceSites: Count[] } | null;
  reviews: { byStatus: Record<string, number>; bySource: Record<string, number>; total: number } | null;
  feedback: Record<string, number> | null;
  workspace: { savedAnswers: number; draftsByStatus: Record<string, number>; cpdMinutes: number; cpdEntries: number } | null;
  unavailable: string[];
};

export async function getInsights(windowDays: number, signal?: AbortSignal): Promise<Insights> {
  const res = await fetch(`${API_URL}/kriton-workspace/insights?window_days=${windowDays}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}`, ...impersonationHeaders() },
    signal,
  });
  if (!res.ok) throw new Error(`Insights request failed (${res.status})`);
  return res.json();
}
