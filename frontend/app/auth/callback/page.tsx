"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { ApiError } from "@/lib/api";
import { homePathFor } from "@/lib/roles";
import { BrandMark } from "@/components/layout/AppHeader";
import { mfaChallengeRequired, provisionAndRefresh } from "@/services/auth.service";

/** OAuth (Google / Microsoft) lands here after Supabase's redirect. The browser client
 * auto-exchanges the URL's auth code for a session on load
 * (detectSessionInUrl, on by default) — this page just waits for that,
 * provisions the local profile on first-ever login (no email-verification
 * gate for OAuth, unlike the password flow), then sends the user on to
 * the dashboard.
 *
 * A first-time Google sign-in with no "Myself / My company" choice becomes an
 * individual Learner account, never a company Admin. Individual accounts are
 * adults-only, so when that confirmation is missing this page asks for it
 * instead of failing the sign-in. */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [needsAdult, setNeedsAdult] = useState(false);
  const [adult, setAdult] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ token: string; metadata: Record<string, unknown> } | null>(null);

  async function complete(accessToken: string, metadata: Record<string, unknown>, adultConfirmed?: boolean) {
    pending.current = { token: accessToken, metadata };
    try {
      const profile = await provisionAndRefresh(accessToken, metadata, { adultConfirmed });
      const needsMfa = await mfaChallengeRequired();
      router.replace(needsMfa ? "/auth/mfa" : homePathFor(profile.role));
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && /18 or older/i.test(err.message) && !adultConfirmed) {
        // New individual account: confirm age here rather than refusing.
        setNeedsAdult(true);
        return;
      }
      if (err instanceof ApiError && (err.status === 403 || err.status === 422)) {
        // Refused sign-up (invite-only deployment): show why, drop the session.
        await supabase.auth.signOut();
        setError(err.message);
        return;
      }
      setError("Could not complete sign-in. Please try again.");
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function finish() {
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        // Give the client SDK a moment to process the redirect URL, then
        // fall back to the auth state change event if still not ready.
        const { data: subscription } = supabase.auth.onAuthStateChange((event, newSession) => {
          if (newSession && !cancelled) {
            subscription.subscription.unsubscribe();
            complete(newSession.access_token, newSession.user.user_metadata ?? {});
          }
        });
        return;
      }

      if (!cancelled) await complete(session.access_token, session.user.user_metadata ?? {});
    }

    finish();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function confirmAdult() {
    if (!pending.current) return;
    setBusy(true);
    await complete(pending.current.token, pending.current.metadata, true);
    setBusy(false);
  }

  async function useCompanySignup() {
    await supabase.auth.signOut();
    router.replace("/signup");
  }

  if (needsAdult && !error) {
    return (
      <main className="flex min-h-screen w-full items-center justify-center bg-bg px-5 py-10 text-ink">
        <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6 shadow-[0_18px_50px_rgba(11,95,122,0.10)]">
          <div className="mb-3 flex items-center gap-3">
            <BrandMark className="h-9 w-9" />
            <div>
              <p className="text-sm font-bold text-ink">ZoikoLogia</p>
              <p className="text-xs text-muted">Governance intelligence workspace</p>
            </div>
          </div>
          <h2 className="text-2xl font-bold text-ink">Create your personal account</h2>
          <p className="mt-1.5 text-sm leading-6 text-muted">
            You&apos;re signing in for the first time. We&apos;ll set up a personal learning account for you.
            Personal accounts are for adult learners.
          </p>
          <label className="mt-4 flex items-start gap-2 text-sm text-ink">
            <input type="checkbox" checked={adult} onChange={(e) => setAdult(e.target.checked)} className="mt-0.5 h-4 w-4 accent-brand" />
            I confirm I am 18 or older.
          </label>
          <button
            type="button"
            disabled={!adult || busy}
            onClick={confirmAdult}
            className="mt-4 inline-flex h-9 w-full items-center justify-center rounded-lg bg-ink px-4 text-sm font-bold text-panel transition-colors hover:bg-brand disabled:opacity-60"
          >
            {busy ? "Setting up…" : "Continue"}
          </button>
          <p className="mt-4 text-center text-sm text-muted">
            Setting up ZoikoLogia for a company?{" "}
            <button type="button" onClick={useCompanySignup} className="font-semibold text-brand hover:underline">
              Sign up and choose My company
            </button>
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-bg text-ink">
      <p className="text-sm text-muted">{error || "Finishing sign-in…"}</p>
    </main>
  );
}
