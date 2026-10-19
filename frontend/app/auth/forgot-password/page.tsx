"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, LockKeyhole, Mail, MailCheck } from "lucide-react";
import { BrandMark } from "@/components/layout/AppHeader";
import { AuthError, resetPassword } from "@/services/auth.service";

type Step = "email" | "sent";

const RESEND_SECONDS = 60;
const input = "h-9 w-full rounded-lg border bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand";

/** Forgot password: Supabase emails a reset link (its own mailer — no
 * third-party email API), which opens /auth/reset-password signed in for the
 * reset, where the new password is chosen. The answer never reveals whether
 * an email has an account. */
export default function ForgotPasswordPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  async function sendLink(e?: FormEvent) {
    e?.preventDefault();
    setError("");
    setNotice("");
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError("Enter the email address you signed up with.");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(email.trim());
      setCooldown(RESEND_SECONDS);
      if (step === "sent") setNotice("A new link is on its way. Use the most recent email.");
      setStep("sent");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not send a reset link. Please try again.");
    } finally {
      setBusy(false);
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

          {step === "email" && (
            <>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Reset your password</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">Enter your email and we&apos;ll send you a link to reset your password.</p>
              <form onSubmit={sendLink} className="mt-3 space-y-2">
                <label htmlFor="reset-email" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Email</label>
                <div className="relative">
                  <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                  <input id="reset-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="sarah@company.com"
                    autoComplete="email" className={`${input} border-line`} />
                </div>
                {error && <p role="alert" className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">{error}</p>}
                <button type="submit" disabled={busy}
                  className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60">
                  {busy ? "Sending link…" : <>Send reset link <ArrowRight size={16} /></>}
                </button>
              </form>
              <p className="mt-3 text-center text-sm text-muted">
                Remembered it?{" "}
                <button type="button" onClick={() => router.push("/login")} className="font-semibold text-brand hover:underline">Sign in</button>
              </p>
            </>
          )}

          {step === "sent" && (
            <>
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 text-xs font-semibold text-brand">
                <MailCheck size={14} /> Check your email
              </div>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Reset link sent</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">
                If an account exists for <span className="font-semibold text-ink">{email.trim()}</span>, we sent a link to reset
                your password. Open it in this browser to choose a new password. Check spam if you don&apos;t see it.
              </p>
              {notice && <p role="status" className="mt-3 rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 text-xs font-medium text-brand">{notice}</p>}
              {error && <p role="alert" className="mt-3 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">{error}</p>}
              <button type="button" onClick={() => router.push("/login")}
                className="mt-3 inline-flex h-9 w-full items-center justify-center rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand">
                Back to sign in
              </button>
              <div className="mt-3 flex items-center justify-between text-sm">
                <button type="button" onClick={() => { setStep("email"); setError(""); setNotice(""); }} className="font-semibold text-brand hover:underline">Use a different email</button>
                <button type="button" disabled={cooldown > 0 || busy} onClick={() => sendLink()} className="font-semibold text-brand hover:underline disabled:text-muted disabled:no-underline">
                  {cooldown > 0 ? `Resend link in ${cooldown}s` : "Resend link"}
                </button>
              </div>
            </>
          )}

          <div className="mt-5 flex items-center justify-center gap-1.5">
            <LockKeyhole size={14} className="text-muted" />
            <span className="text-xs text-muted">Reset links are sent by email only, work once and expire.</span>
          </div>
        </div>
      </div>
    </main>
  );
}
