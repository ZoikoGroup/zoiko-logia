"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, KeyRound, ShieldCheck } from "lucide-react";
import { AuthError, signOut, verifyTotpSignIn } from "@/services/auth.service";
import { BrandMark } from "@/components/layout/AppHeader";

/** Second sign-in step for accounts with a verified authenticator app. The
 * session already exists at aal1 (password or OAuth); proxy.ts keeps every
 * other page out of reach until this challenge raises it to aal2. */
export default function MfaChallengePage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from your authenticator app.");
      return;
    }
    setSubmitting(true);
    try {
      await verifyTotpSignIn(code);
      router.replace("/");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not verify the code. Please try again.");
      setSubmitting(false);
    }
  }

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
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

          <div className="mb-3">
            <h2 className="text-2xl font-bold tracking-normal text-ink">Two-step verification</h2>
            <p className="mt-1.5 text-sm leading-6 text-muted">
              Open your authenticator app and enter the 6-digit code for ZoikoLogia.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-2">
            <div>
              <label htmlFor="mfa-code" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
                Verification code
              </label>
              <div className="relative">
                <KeyRound size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                <input
                  id="mfa-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder="123456"
                  className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm tracking-[0.3em] text-ink placeholder:tracking-normal placeholder:text-muted outline-none focus:border-brand"
                />
              </div>
            </div>

            {error && (
              <p role="alert" className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60"
            >
              {submitting ? "Verifying..." : (
                <>
                  Verify and continue
                  <ArrowRight size={16} />
                </>
              )}
            </button>
          </form>

          <p className="mt-3 text-center text-sm text-muted">
            Lost access to your authenticator?{" "}
            <button type="button" onClick={handleSignOut} className="font-semibold text-brand hover:underline">
              Sign out
            </button>{" "}
            and ask your administrator to reset it.
          </p>

          <div className="mt-5 flex items-center justify-center gap-1.5">
            <ShieldCheck size={14} className="text-muted" />
            <span className="text-xs text-muted">Required because this account has two-step verification on.</span>
          </div>
        </div>
      </div>
    </main>
  );
}
