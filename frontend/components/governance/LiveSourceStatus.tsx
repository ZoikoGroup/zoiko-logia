"use client";

import { useEffect } from "react";

export function LiveSourceStatus({ loading, error, signedOut, reload }: {
  loading: boolean; error: string; signedOut: boolean; reload: () => void;
}) {
  useEffect(() => {
    if (signedOut) return;
    const refreshIfVisible = () => { if (document.visibilityState === "visible") reload(); };
    const timer = window.setInterval(refreshIfVisible, 60_000);
    window.addEventListener("focus", refreshIfVisible);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refreshIfVisible); };
  }, [reload, signedOut]);
  return <div className="flex items-center justify-between gap-3 mb-4 text-xs" aria-live="polite">
    <span className={error ? "text-bad" : "text-muted"}>
      {signedOut ? "Sign in to view source records." : error || (loading ? "Loading current records…" : "Loaded from connected records.")}
    </span>
    <button type="button" onClick={reload} disabled={loading || signedOut} className="text-brand disabled:opacity-50">Refresh</button>
  </div>;
}
