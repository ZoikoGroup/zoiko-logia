"use client";

export function LiveSourceStatus({ loading, error, signedOut, reload, showRefresh = true }: {
  loading: boolean; error: string; signedOut: boolean; reload: () => void; showRefresh?: boolean;
}) {
  return <div className="flex items-center justify-between gap-3 mb-4 text-xs" aria-live="polite">
    <span className={error ? "text-bad" : "text-muted"}>
      {signedOut ? "Sign in to view source records." : error || (loading ? "Loading current records…" : "Loaded from connected records.")}
    </span>
    {(showRefresh || error) && <button type="button" onClick={reload} disabled={loading || signedOut} className="text-brand disabled:opacity-50">{error ? "Try again" : "Refresh"}</button>}
  </div>;
}
