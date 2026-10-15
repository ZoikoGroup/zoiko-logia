"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, Eye, EyeOff, KeyRound, LockKeyhole, Mail, ShieldCheck, X } from "lucide-react";
import { ApiError, requestPasswordResetCode, resetPasswordWithCode } from "@/lib/api";
import { BrandMark } from "@/components/layout/AppHeader";

type Step = "email" | "reset" | "done";

// Mirrors the backend rule (identity/password_reset.py PASSWORD_RE).
const RULES: { label: string; test: (p: string) => boolean }[] = [
  { label: "At least 8 characters", test: (p) => p.length >= 8 },
  { label: "An uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "A lowercase letter", test: (p) => /[a-z]/.test(p) },
  { label: "A number", test: (p) => /\d/.test(p) },
];
const RESEND_SECONDS = 60;
const input = "h-9 w-full rounded-lg border bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand";

/** Forgot password, modelled on ZoikoStream: the backend emails a 6-digit
 * code from ZoikoLogia's own sender; the person enters it here with the new
 * password and its confirmation. The answer never reveals whether an email
 * has an account. */
export default function ForgotPasswordPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [ttl, setTtl] = useState(15);
  const [codeLength, setCodeLength] = useState(6);
  const [cooldown, setCooldown] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  async function sendCode(e?: FormEvent) {
    e?.preventDefault();
    setError("");
    setNotice("");
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError("Enter the email address you signed up with.");
      return;
    }
    setBusy(true);
    try {
      const res = await requestPasswordResetCode(email.trim());
      if (res.expires_in_minutes > 0) setTtl(res.expires_in_minutes);
      if (res.code_length > 0) setCodeLength(res.code_length);
      setCooldown(RESEND_SECONDS);
      if (step === "reset") setNotice("A new code is on its way. The previous code no longer works.");
      setStep("reset");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send a code. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const digits = code.replace(/\D/g, "");
  const passwordOk = RULES.every((r) => r.test(password));
  const canReset = digits.length === codeLength && passwordOk && password === confirm;

  async function submitReset(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await resetPasswordWithCode(email.trim(), digits, password);
      setStep("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reset your password. Please try again.");
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
              <p className="mt-1.5 text-sm leading-6 text-muted">Enter your email and we&apos;ll send you a 6-digit verification code.</p>
              <form onSubmit={sendCode} className="mt-3 space-y-2">
                <label htmlFor="reset-email" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Email</label>
                <div className="relative">
                  <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                  <input id="reset-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="sarah@company.com"
                    autoComplete="email" className={`${input} border-line`} />
                </div>
                {error && <p role="alert" className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">{error}</p>}
                <button type="submit" disabled={busy}
                  className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60">
                  {busy ? "Sending code…" : <>Send code <ArrowRight size={16} /></>}
                </button>
              </form>
              <p className="mt-3 text-center text-sm text-muted">
                Remembered it?{" "}
                <button type="button" onClick={() => router.push("/login")} className="font-semibold text-brand hover:underline">Sign in</button>
              </p>
            </>
          )}

          {step === "reset" && (
            <>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Enter your code</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">
                If an account exists for <span className="font-semibold text-ink">{email.trim()}</span>, we sent a {codeLength}-digit code.
                It expires in {ttl} minutes. Check spam if you don&apos;t see it.
              </p>
              <form onSubmit={submitReset} className="mt-3 space-y-2">
                <div>
                  <label htmlFor="reset-code" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Verification code</label>
                  <div className="relative">
                    <ShieldCheck size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                    <input id="reset-code" inputMode="numeric" autoComplete="one-time-code" maxLength={codeLength + 2} value={code}
                      onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ""))} placeholder={"•".repeat(codeLength)}
                      className={`${input} border-line font-mono tracking-[0.4em]`} />
                  </div>
                </div>
                <div>
                  <label htmlFor="new-password" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">New Password</label>
                  <div className="relative">
                    <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                    <input id="new-password" type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)}
                      placeholder="At least 8 characters" autoComplete="new-password" className={`${input} border-line pr-10`} />
                    <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide password" : "Show password"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink">{show ? <EyeOff size={16} /> : <Eye size={16} />}</button>
                  </div>
                </div>
                <div>
                  <label htmlFor="confirm-password" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Confirm New Password</label>
                  <div className="relative">
                    <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                    <input id="confirm-password" type={show ? "text" : "password"} value={confirm} onChange={(e) => setConfirm(e.target.value)}
                      placeholder="Re-enter the new password" autoComplete="new-password" aria-invalid={confirm.length > 0 && confirm !== password}
                      className={`${input} ${confirm.length > 0 && confirm !== password ? "border-bad" : "border-line"}`} />
                  </div>
                </div>
                <ul className="grid grid-cols-2 gap-x-3 gap-y-1 pt-1 text-xs" aria-label="Password requirements">
                  {[...RULES, { label: "Passwords match", test: (p: string) => p.length > 0 && p === confirm }].map((rule) => {
                    const ok = rule.test(password);
                    return <li key={rule.label} className={`flex items-center gap-1.5 ${ok ? "text-ok" : "text-muted"}`}>{ok ? <Check size={13} /> : <X size={13} />}{rule.label}</li>;
                  })}
                </ul>
                {notice && <p role="status" className="rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 text-xs font-medium text-brand">{notice}</p>}
                {error && <p role="alert" className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">{error}</p>}
                <button type="submit" disabled={busy || !canReset}
                  className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60">
                  {busy ? "Updating password…" : "Set new password"}
                </button>
              </form>
              <div className="mt-3 flex items-center justify-between text-sm">
                <button type="button" onClick={() => { setStep("email"); setCode(""); setError(""); setNotice(""); }} className="font-semibold text-brand hover:underline">Use a different email</button>
                <button type="button" disabled={cooldown > 0 || busy} onClick={() => sendCode()} className="font-semibold text-brand hover:underline disabled:text-muted disabled:no-underline">
                  {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
                </button>
              </div>
            </>
          )}

          {step === "done" && (
            <>
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 text-xs font-semibold text-brand">
                <KeyRound size={14} /> Password updated
              </div>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Your password is set</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">You were signed out on every device. Sign in with your new password.</p>
              <button type="button" onClick={() => router.push("/login")}
                className="mt-3 inline-flex h-9 w-full items-center justify-center rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand">
                Back to sign in
              </button>
            </>
          )}

          <div className="mt-5 flex items-center justify-center gap-1.5">
            <LockKeyhole size={14} className="text-muted" />
            <span className="text-xs text-muted">Codes are sent by email only, work once and expire.</span>
          </div>
        </div>
      </div>
    </main>
  );
}
