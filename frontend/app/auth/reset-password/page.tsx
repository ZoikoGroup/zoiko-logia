"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, KeyRound, LockKeyhole } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { AuthError, updatePassword } from "@/services/auth.service";
import { BrandMark } from "@/components/layout/AppHeader";

type Stage = "detecting" | "ready" | "success" | "invalid";

/** Completion side of the reset flow. Supabase redirects from the emailed
 * link to this page with the tokens in the URL hash
 * (#access_token=…&type=recovery) — the client SDK's detectSessionInUrl
 * (on by default) auto-exchanges that hash for a single-use recovery
 * session, which surfaces as a PASSWORD_RECOVERY auth event. This page
 * waits for that event (or an already-present session), then collects the
 * new password and calls supabase.auth.updateUser — the same SDK call the
 * backend has no hand in, by design. */
export default function ResetPasswordPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("detecting");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function detectRecoverySession() {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (session && !cancelled) setStage("ready");
    }

    const { data: subscription } = supabase.auth.onAuthStateChange((event, session) => {
      // PASSWORD_RECOVERY fires when the SDK finishes exchanging the hash
      // tokens from the email link. Session can be the freshly-created
      // recovery session; treat a plain existing session the same way so a
      // signed-in user who clicks the link can still reset right here.
      if ((event === "PASSWORD_RECOVERY" || session) && !cancelled) {
        subscription.subscription.unsubscribe();
        setStage("ready");
      }
    });

    detectRecoverySession();

    // The SDK exchanges the hash on load; if nothing arrived after a grace
    // window, the link is stale, already used, or wasn't a recovery link.
    const timeout = setTimeout(() => {
      if (!cancelled) setStage((current) => (current === "detecting" ? "invalid" : current));
    }, 3000);

    return () => {
      cancelled = true;
      subscription.subscription.unsubscribe();
      clearTimeout(timeout);
    };
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await updatePassword(password);
      setStage("success");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not update your password. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-bg px-5 py-10 text-ink">
      <div className="relative w-full max-w-md">
        <div className="relative overflow-hidden rounded-2xl border border-line bg-panel p-5 shadow-[0_18px_50px_rgba(11,95,122,0.10)] sm:p-6">
          <div className="mb-3 flex items-center gap-3">
            <BrandMark className="h-9 w-9" />
            <div>
              <p className="text-sm font-bold text-ink">ZoikoLogia</p>
              <p className="text-xs text-muted">Governance intelligence workspace</p>
            </div>
          </div>

          {stage === "detecting" && (
            <>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Choose a new password</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">Checking your reset link…</p>
            </>
          )}

          {stage === "invalid" && (
            <>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Reset link invalid</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">
                This link is expired, already used, or wasn&apos;t a password reset link. Request a fresh one and
                use it right away.
              </p>
              <p className="mt-3 text-center text-sm text-muted">
                <button
                  type="button"
                  onClick={() => router.push("/auth/forgot-password")}
                  className="font-semibold text-brand hover:underline"
                >
                  Send a new link
                </button>
              </p>
            </>
          )}

          {stage === "success" && (
            <>
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 text-xs font-semibold text-brand">
                <KeyRound size={14} />
                Password updated
              </div>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Your password is set</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">
                You can sign in with your new password now. Sign out of your other devices if you&apos;d like to
                revoke them.
              </p>
              <button
                type="button"
                onClick={() => router.push("/login")}
                className="mt-3 inline-flex h-9 w-full items-center justify-center rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand"
              >
                Back to sign in
              </button>
            </>
          )}

          {stage === "ready" && (
            <>
              <div className="mb-3">
                <h2 className="text-2xl font-bold tracking-normal text-ink">Choose a new password</h2>
                <p className="mt-1.5 text-sm leading-6 text-muted">
                  Must be at least 8 characters with an uppercase letter, a lowercase letter, and a number.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-2">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
                    New Password
                  </label>
                  <div className="relative">
                    <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                    <input
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="At least 8 characters"
                      autoComplete="new-password"
                      className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-10 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                {error && (
                  <p className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60"
                >
                  {submitting ? "Updating password..." : "Set new password"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </main>
  );
}