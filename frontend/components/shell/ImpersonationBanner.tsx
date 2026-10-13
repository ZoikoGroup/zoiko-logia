"use client";

import { useEffect, useState } from "react";
import { Eye } from "lucide-react";
import { endImpersonation, getAuthToken } from "@/lib/api";
import {
  IMPERSONATION_EVENT,
  clearImpersonation,
  getImpersonation,
  type ActiveImpersonation,
} from "@/lib/impersonation";

/** Persistent, non-dismissable notice while an Admin views the workspace as
 * another user. The spec requires impersonation to be visible for its whole
 * duration; the only way to hide this is to end the session. */
export function ImpersonationBanner() {
  const [active, setActive] = useState<ActiveImpersonation | null>(null);
  const [ending, setEnding] = useState(false);

  useEffect(() => {
    const sync = () => setActive(getImpersonation());
    // Read on mount (sessionStorage is client-only), on every change, and
    // periodically so an expired session clears itself.
    const initial = window.setTimeout(sync, 0);
    const timer = window.setInterval(sync, 15_000);
    window.addEventListener(IMPERSONATION_EVENT, sync);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
      window.removeEventListener(IMPERSONATION_EVENT, sync);
    };
  }, []);

  if (!active) return null;

  async function handleEnd() {
    if (!active) return;
    setEnding(true);
    try {
      await endImpersonation(getAuthToken(), active.sessionId);
    } catch {
      // Already ended or expired server-side; clearing locally is all that's left.
    }
    clearImpersonation();
    // Reload so every view re-reads as the Admin again.
    window.location.assign("/users-teams");
  }

  const endsAt = new Date(active.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      role="status"
      // Fixed rather than in-flow: the app shell is a flex row and Ask Kriton
      // has no shell at all, so this is the one placement visible everywhere.
      className="fixed bottom-4 left-1/2 z-50 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-full border border-warn/50 bg-panel px-4 py-2 text-sm text-ink shadow-[0_12px_32px_rgba(21,25,34,0.22)]"
    >
      <Eye size={16} aria-hidden="true" className="text-warn" />
      <span>
        Viewing as <strong>{active.targetName}</strong> ({active.targetRole}) — read-only, ends at {endsAt}
      </span>
      <button
        type="button"
        onClick={handleEnd}
        disabled={ending}
        className="rounded-md border border-ink/20 bg-panel px-2.5 py-0.5 text-xs font-semibold hover:bg-soft disabled:opacity-60"
      >
        {ending ? "Ending..." : "End view"}
      </button>
    </div>
  );
}
