"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, ArrowRight, LockKeyhole } from "lucide-react";
import { AuthError, resetPassword } from "@/services/auth.service";
import { BrandMark } from "@/components/layout/AppHeader";

/** Request side of the reset flow: type your email, Supabase sends a
 * password-recovery link. That link points at /auth/reset-password (the
 * redirectTo passed to resetPasswordForEmail), which must be in the
 * Supabase project's Auth → URL Configuration allow-list. */
export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!email.trim()) {
      setError("Enter the email address you signed up with.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(email.trim());
      setSent(true);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not send a reset link. Please try again.");
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

          {sent ? (
            <>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Check your email</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">
                If an account exists for <span className="font-semibold text-ink">{email}</span>, a password
                reset link is on its way. It may take a few minutes — and check spam if it doesn&apos;t arrive.
              </p>
              <p className="mt-3 text-center text-sm text-muted">
                <button
                  type="button"
                  onClick={() => router.push("/login")}
                  className="font-semibold text-brand hover:underline"
                >
                  Back to sign in
                </button>
              </p>
            </>
          ) : (
            <>
              <div className="mb-3">
                <h2 className="text-2xl font-bold tracking-normal text-ink">Reset your password</h2>
                <p className="mt-1.5 text-sm leading-6 text-muted">
                  Enter your work email and we&apos;ll send you a link to choose a new password.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-2">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
                    Work Email
                  </label>
                  <div className="relative">
                    <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="sarah@company.com"
                      autoComplete="email"
                      className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
                    />
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
                  {submitting ? "Sending link..." : (
                    <>
                      Send reset link
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </form>

              <p className="mt-3 text-center text-sm text-muted">
                Remembered it?{" "}
                <button
                  type="button"
                  onClick={() => router.push("/login")}
                  className="font-semibold text-brand hover:underline"
                >
                  Sign in
                </button>
              </p>
            </>
          )}

          <div className="mt-5 flex items-center justify-center gap-1.5">
            <LockKeyhole size={14} className="text-muted" />
            <span className="text-xs text-muted">Link sent by email only — we never show your password.</span>
          </div>
        </div>
      </div>
    </main>
  );
}