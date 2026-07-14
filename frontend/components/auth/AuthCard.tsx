"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Building2,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  ShieldCheck,
  User,
} from "lucide-react";
import {
  AuthError,
  signInWithGoogle,
  signInWithPassword,
  signUp,
  validateSignUp,
  type FieldErrors,
} from "@/services/auth.service";
import { BrandMark } from "@/components/layout/AppHeader";

type Mode = "signin" | "signup";

export function AuthCard({ initialMode }: { initialMode: Mode }) {
  const [mode, setMode] = useState<Mode>(initialMode);

  return (
    <main className="min-h-screen w-full bg-bg text-ink">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_460px]">
        <section className="relative hidden overflow-hidden border-r border-line bg-panel lg:block">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_20%,rgba(22,121,154,0.18),transparent_34%),radial-gradient(circle_at_76%_72%,rgba(243,196,55,0.16),transparent_28%)]" />
          <div className="relative flex h-full flex-col justify-between p-10">
            <div className="flex items-center gap-3">
              <BrandMark className="h-12 w-12" />
              <div>
                <p className="text-sm font-bold text-ink">ZoikoLogia</p>
                <p className="text-xs text-muted">Governance intelligence workspace</p>
              </div>
            </div>

            <div className="max-w-2xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-semibold text-brand">
                <BrainCircuit size={14} />
                Ask Kriton after sign in
              </div>
              <h1 className="text-5xl font-bold leading-tight tracking-normal text-ink">
                Source-governed AI for accounting decisions.
              </h1>
              <p className="mt-5 max-w-xl text-sm leading-7 text-muted">
                Review standards, attach documents, route risk, and keep every Kriton answer tied to audit evidence.
              </p>
            </div>

            <div className="grid max-w-2xl grid-cols-3 gap-3">
              {[
                { icon: BookOpenCheck, label: "Source checks" },
                { icon: ShieldCheck, label: "Safety routing" },
                { icon: LockKeyhole, label: "Audit trail" },
              ].map(({ icon: Icon, label }) => (
                <div key={label} className="rounded-lg border border-line bg-bg/70 p-4 shadow-[0_10px_30px_rgba(11,95,122,0.06)]">
                  <Icon size={18} className="text-brand" />
                  <p className="mt-3 text-xs font-bold text-ink">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="relative flex min-h-screen items-center justify-center overflow-hidden px-5 py-10">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_15%,rgba(22,121,154,0.12),transparent_38%),radial-gradient(circle_at_82%_85%,rgba(243,196,55,0.10),transparent_32%)]" />
          <div className="relative w-full max-w-md">
            <div className="relative overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_18px_50px_rgba(11,95,122,0.10)]">
              <div className="grid">
                <SignInPanel active={mode === "signin"} onSwitchToSignup={() => setMode("signup")} />
                <SignUpPanel active={mode === "signup"} onSwitchToSignin={() => setMode("signin")} />
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function panelClassName(active: boolean, direction: "left" | "right") {
  const hiddenTransform = direction === "left" ? "-translate-x-full" : "translate-x-full";
  return [
    "col-start-1 row-start-1 w-full p-5 sm:p-6",
    "transition-all duration-300 ease-out",
    active ? "translate-x-0 opacity-100" : `${hiddenTransform} opacity-0 pointer-events-none`,
  ].join(" ");
}

function SignInPanel({ active, onSwitchToSignup }: { active: boolean; onSwitchToSignup: () => void }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [googleSubmitting, setGoogleSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signInWithPassword(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not reach the server. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogle() {
    setError("");
    setGoogleSubmitting(true);
    try {
      await signInWithGoogle();
      // Browser navigates away to Google — no further local state change needed.
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not start Google sign-in.");
      setGoogleSubmitting(false);
    }
  }

  return (
    <div className={panelClassName(active, "left")} aria-hidden={!active}>
      <div className="mb-3">
        <h2 className="text-2xl font-bold tracking-normal text-ink">Sign in to ZoikoLogia</h2>
        <p className="mt-1.5 text-sm leading-6 text-muted">
          Continue to your Ask Kriton governance workspace.
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
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
        </div>
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label className="text-xs font-semibold uppercase tracking-wide text-muted">Password</label>
            <button
              type="button"
              title="Coming soon"
              tabIndex={active ? 0 : -1}
              className="text-xs font-semibold text-brand hover:underline"
            >
              Forgot password?
            </button>
          </div>
          <div className="relative">
            <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-10 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              tabIndex={active ? 0 : -1}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted">
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
            tabIndex={active ? 0 : -1}
            className="h-4 w-4 rounded border-line accent-brand"
          />
          Keep me signed in on this device
        </label>

        {error && (
          <p className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          tabIndex={active ? 0 : -1}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60"
        >
          {!submitting && <ArrowRight size={16} />}
          {submitting ? "Signing in..." : "Sign in"}
        </button>

        <div className="flex items-center gap-3 py-0.5">
          <div className="h-px flex-1 bg-line" />
          <span className="text-xs font-medium uppercase tracking-wide text-muted">or continue with</span>
          <div className="h-px flex-1 bg-line" />
        </div>

        <div className="grid grid-cols-1 gap-3">
          <button
            type="button"
            onClick={handleGoogle}
            disabled={googleSubmitting}
            tabIndex={active ? 0 : -1}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-line bg-soft text-sm font-semibold text-ink transition-colors hover:bg-line/40 disabled:opacity-60"
          >
            <GoogleIcon />
            {googleSubmitting ? "Redirecting..." : "Google"}
          </button>
        </div>
      </form>

      <p className="mt-3 text-center text-xs leading-5 text-muted">
        By signing in you agree to our{" "}
        <button type="button" title="Coming soon" tabIndex={active ? 0 : -1} className="underline hover:text-ink">
          Terms of Service
        </button>{" "}
        and{" "}
        <button type="button" title="Coming soon" tabIndex={active ? 0 : -1} className="underline hover:text-ink">
          Privacy Policy
        </button>
      </p>

      <p className="mt-3 text-center text-sm text-muted">
        Don&apos;t have an account?{" "}
        <button
          type="button"
          onClick={onSwitchToSignup}
          tabIndex={active ? 0 : -1}
          className="font-semibold text-brand hover:underline"
        >
          Create one free.
        </button>
      </p>
    </div>
  );
}

function SignUpPanel({ active, onSwitchToSignin }: { active: boolean; onSwitchToSignin: () => void }) {
  const router = useRouter();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState("");
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [googleSubmitting, setGoogleSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    const fields = { firstName, lastName, email, companyName: company, password };
    const errors = validateSignUp(fields);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      await signUp(fields);
      setSuccess(true);
      setTimeout(() => router.push("/login"), 2000);
    } catch (err) {
      setFormError(err instanceof AuthError ? err.message : "Could not create your account. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogle() {
    setFormError("");
    setGoogleSubmitting(true);
    try {
      await signInWithGoogle();
    } catch (err) {
      setFormError(err instanceof AuthError ? err.message : "Could not start Google sign-in.");
      setGoogleSubmitting(false);
    }
  }

  if (success) {
    return (
      <div className={panelClassName(active, "right")} aria-hidden={!active}>
        <div className="mb-3">
          <h2 className="text-2xl font-bold tracking-normal text-ink">Check your email</h2>
          <p className="mt-1.5 text-sm leading-6 text-muted">
            Account created successfully. Please check your email and verify your account before signing in.
          </p>
        </div>
        <p className="mt-3 text-center text-sm text-muted">
          Redirecting to{" "}
          <button type="button" onClick={() => router.push("/login")} className="font-semibold text-brand hover:underline">
            sign in
          </button>
          ...
        </p>
      </div>
    );
  }

  return (
    <div className={panelClassName(active, "right")} aria-hidden={!active}>
      <div className="mb-3">
        <h2 className="text-2xl font-bold tracking-normal text-ink">Start for free</h2>
        <p className="mt-1.5 text-sm leading-6 text-muted">
          Starting with ZoikoLogia Starter — free, no credit card needed.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
              First Name
            </label>
            <div className="relative">
              <User size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="Sarah"
                autoComplete="given-name"
                tabIndex={active ? 0 : -1}
                className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
              />
            </div>
            {fieldErrors.firstName && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.firstName}</p>}
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
              Last Name
            </label>
            <div className="relative">
              <User size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Chen"
                autoComplete="family-name"
                tabIndex={active ? 0 : -1}
                className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
              />
            </div>
            {fieldErrors.lastName && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.lastName}</p>}
          </div>
        </div>

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
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
          {fieldErrors.email && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.email}</p>}
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Company Name
          </label>
          <div className="relative">
            <Building2 size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
              autoComplete="organization"
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
          {fieldErrors.companyName && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.companyName}</p>}
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Password
          </label>
          <div className="relative">
            <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              autoComplete="new-password"
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-10 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              tabIndex={active ? 0 : -1}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {fieldErrors.password && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.password}</p>}
        </div>

        {formError && (
          <p className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
            {formError}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          tabIndex={active ? 0 : -1}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60"
        >
          {submitting ? "Creating account..." : "Continue"}
          {!submitting && <ArrowRight size={16} />}
        </button>

        <div className="flex items-center gap-3 py-0.5">
          <div className="h-px flex-1 bg-line" />
          <span className="text-xs font-medium uppercase tracking-wide text-muted">or continue with</span>
          <div className="h-px flex-1 bg-line" />
        </div>

        <div className="grid grid-cols-1 gap-3">
          <button
            type="button"
            onClick={handleGoogle}
            disabled={googleSubmitting}
            tabIndex={active ? 0 : -1}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-line bg-soft text-sm font-semibold text-ink transition-colors hover:bg-line/40 disabled:opacity-60"
          >
            <GoogleIcon />
            {googleSubmitting ? "Redirecting..." : "Google"}
          </button>
        </div>
      </form>

      <div className="mt-5 flex items-center justify-center gap-1.5">
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={i === 0 ? "h-1.5 w-5 rounded-full bg-ink" : "h-1.5 w-1.5 rounded-full bg-line"} />
        ))}
      </div>

      <p className="mt-3 text-center text-sm text-muted">
        Already have an account?{" "}
        <button
          type="button"
          onClick={onSwitchToSignin}
          tabIndex={active ? 0 : -1}
          className="font-semibold text-brand hover:underline"
        >
          Sign in
        </button>
      </p>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.47c-.28 1.5-1.13 2.77-2.4 3.62v3h3.88c2.27-2.09 3.57-5.17 3.57-8.81Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.07 7.95-2.92l-3.88-3c-1.08.72-2.46 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.96H1.27v3.11C3.25 21.3 7.31 24 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.27a7.2 7.2 0 0 1 0-4.54v-3.1H1.27a12 12 0 0 0 0 10.74l4-3.1Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.76 0 3.35.61 4.6 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0 7.31 0 3.25 2.7 1.27 6.63l4 3.1C6.22 6.86 8.87 4.75 12 4.75Z"
      />
    </svg>
  );
}
