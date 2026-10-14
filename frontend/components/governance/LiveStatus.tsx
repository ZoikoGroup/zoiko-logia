"use client";

import { AlertTriangle } from "lucide-react";

export function formatCount(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString();
}

/** Backend timestamps are UTC; some columns are stored without a zone
 * ("2026-10-13T04:59:59"), which the browser would read as local time. */
export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const text = iso.includes("T") ? iso : iso.replace(" ", "T");
  const date = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(text) ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatWhen(iso: string | null | undefined): string {
  const date = parseUtc(iso);
  if (!date) return "—";
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function LoadError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl border border-bad/30 bg-bad/5 px-4 py-3 text-xs text-bad">
      <AlertTriangle size={14} />
      <span className="flex-1">{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="font-semibold underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

export function errorMessage(error: unknown, what: string): string {
  const detail = error instanceof Error ? error.message : "";
  if (/permission/i.test(detail)) return `Your role cannot view ${what}. (${detail})`;
  if (detail && !/fetch|network/i.test(detail)) return `Could not load ${what}: ${detail}`;
  return `Could not load ${what} — the backend did not respond. Check it is running and try again.`;
}
