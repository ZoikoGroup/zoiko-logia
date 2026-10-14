"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div role="status" className="space-y-4" aria-label={label}>
      {[0, 1, 2].map((i) => <div key={i} className="h-28 animate-pulse rounded-2xl border border-line bg-panel" />)}
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-2xl border border-bad/30 bg-bad/5 p-5 text-sm">
      <p className="font-semibold text-bad">Could not load live data</p>
      <p className="mt-1 text-muted">{message}</p>
      <button onClick={onRetry} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 font-semibold text-ink hover:bg-soft"><RefreshCw size={14} /> Try again</button>
    </div>
  );
}

export function SignedOutBlock() {
  return (
    <div className="rounded-2xl border border-line bg-panel p-5 text-sm">
      <p className="font-semibold text-ink">Sign in to see your live workspace</p>
      <p className="mt-1 text-muted">These figures are counted from your workspace&apos;s records, so they need a signed-in account.</p>
      <Link href="/login" className="mt-3 inline-block font-semibold text-brand">Sign in</Link>
    </div>
  );
}

export function EmptyRow({ children }: { children: React.ReactNode }) {
  return <p className="px-5 py-6 text-sm text-muted">{children}</p>;
}

export function RefreshButton({ onClick, loading, generatedAt }: { onClick: () => void; loading: boolean; generatedAt?: string }) {
  const time = generatedAt ? new Date(generatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
  return (
    <button onClick={onClick} disabled={loading} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft disabled:opacity-60" title={time ? `Last updated ${time}` : undefined}>
      <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> {loading ? "Refreshing" : "Refresh"}
    </button>
  );
}
