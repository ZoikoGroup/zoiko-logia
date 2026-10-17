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
  GraduationCap,
  LockKeyhole,
  Mail,
  ShieldCheck,
  User,
} from "lucide-react";
import {
  ADULT_ONLY_MESSAGE,
  AuthError,
  EmailNotConfirmedError,
  ENABLED_OAUTH_PROVIDERS,
  OAUTH_PROVIDER_LABELS,
  PUBLIC_SIGNUP_ENABLED,
  rememberSignupChoice,
  resendConfirmation,
  signInWithOAuthProvider,
  signInWithPassword,
  signUp,
  validateSignUp,
  type AccountType,
  type FieldErrors,
  type OAuthProvider,
} from "@/services/auth.service";
import { BrandMark } from "@/components/layout/AppHeader";

type Mode = "signin" | "signup";

export function AuthCard({ initialMode }: { initialMode: Mode }) {
  // Invite-only deployments never show the sign-up form, even at /signup.
  const [mode, setMode] = useState<Mode>(PUBLIC_SIGNUP_ENABLED ? initialMode : "signin");

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
                <SignInPanel
                  active={mode === "signin"}
                  onSwitchToSignup={PUBLIC_SIGNUP_ENABLED ? () => setMode("signup") : undefined}
                />
                {PUBLIC_SIGNUP_ENABLED && (
                  <SignUpPanel active={mode === "signup"} onSwitchToSignin={() => setMode("signin")} />
                )}
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

function SignInPanel({ active, onSwitchToSignup }: { active: boolean; onSwitchToSignup?: () => void }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");
    setUnconfirmed(false);
    setSubmitting(true);
    try {
      const { mfaRequired, home } = await signInWithPassword(email.trim(), password);
      router.push(mfaRequired ? "/auth/mfa" : home);
    } catch (err) {
      setUnconfirmed(err instanceof EmailNotConfirmedError);
      setError(err instanceof AuthError ? err.message : "Something went wrong while signing you in. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setError("");
    setNotice("");
    try {
      await resendConfirmation(email.trim());
      setUnconfirmed(false);
      setNotice("Verification email sent. Open the link in it, then sign in.");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not resend the verification email.");
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
              onClick={() => router.push("/auth/forgot-password")}
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
          <p role="alert" className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
            {error}
            {unconfirmed && (
              <>
                {" "}
                <button type="button" onClick={handleResend} className="font-semibold underline">
                  Resend verification email
                </button>
              </>
            )}
          </p>
        )}
        {notice && (
          <p role="status" className="rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-xs font-medium text-ok">
            {notice}
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

        <OAuthButtons active={active} onError={setError} />
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

      {onSwitchToSignup ? (
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
      ) : (
        <p className="mt-3 text-center text-sm text-muted">
          Access is by invitation. Ask your administrator for an account.
        </p>
      )}
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
  // Company stays the default: it is what sign-up always did, and a company
  // owner who misses the toggle would otherwise land as a Learner.
  const [accountType, setAccountType] = useState<AccountType>("company");
  const [adultConfirmed, setAdultConfirmed] = useState(false);
  const isCompany = accountType === "company";

  /** Runs before an OAuth redirect. Google sign-up always creates a personal
   * Learner account (the backend enforces it), so only the adult
   * confirmation travels to /auth/callback. */
  function prepareOAuthSignup(): boolean {
    if (!adultConfirmed) {
      setFieldErrors({ adultConfirmed: ADULT_ONLY_MESSAGE });
      return false;
    }
    rememberSignupChoice({ accountType: "individual", adultConfirmed });
    return true;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    const fields = { accountType, firstName, lastName, email, companyName: company, password, adultConfirmed };
    const errors = validateSignUp(fields);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      const { home } = await signUp(fields);
      if (home) {
        // No email confirmation required on this project: already signed in.
        router.push(home);
        return;
      }
      setSuccess(true);
    } catch (err) {
      setFormError(err instanceof AuthError ? err.message : "Could not create your account. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <div className={panelClassName(active, "right")} aria-hidden={!active}>
        <div className="mb-3">
          <h2 className="text-2xl font-bold tracking-normal text-ink">Check your email</h2>
          <p className="mt-1.5 text-sm leading-6 text-muted">
            Account created. We sent a confirmation link to <span className="font-semibold text-ink">{email}</span>.
            Open it to verify your address and you&apos;ll be signed in automatically.
          </p>
        </div>
        <p className="mt-3 text-center text-sm text-muted">
          Already verified?{" "}
          <button type="button" onClick={onSwitchToSignin} className="font-semibold text-brand hover:underline">
            Sign in
          </button>
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

      <div role="radiogroup" aria-label="Who is this account for?" className="mb-3">
        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">I&apos;m signing up for</p>
        <div className="grid grid-cols-2 gap-2">
          {[
            { value: "individual" as const, label: "Myself", hint: "Learn & practise", icon: GraduationCap },
            { value: "company" as const, label: "My company", hint: "Invite your team", icon: Building2 },
          ].map(({ value, label, hint, icon: Icon }) => {
            const selected = accountType === value;
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={selected}
                tabIndex={active ? 0 : -1}
                onClick={() => {
                  setAccountType(value);
                  setFieldErrors({});
                }}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors ${
                  selected ? "border-brand bg-brand/10" : "border-line bg-soft hover:bg-line/40"
                }`}
              >
                <Icon size={16} className={selected ? "text-brand" : "text-muted"} />
                <span>
                  <span className="block text-sm font-semibold text-ink">{label}</span>
                  <span className="block text-[11px] text-muted">{hint}</span>
                </span>
              </button>
            );
          })}
        </div>
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
            {isCompany ? "Work Email" : "Email"}
          </label>
          <div className="relative">
            <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={isCompany ? "sarah@company.com" : "sarah@gmail.com"}
              autoComplete="email"
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
          {fieldErrors.email && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.email}</p>}
        </div>

        {isCompany && (
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
        )}

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

        {!isCompany && (
          <div>
            <label className="flex items-start gap-2 text-xs text-ink">
              <input
                type="checkbox"
                checked={adultConfirmed}
                onChange={(e) => setAdultConfirmed(e.target.checked)}
                tabIndex={active ? 0 : -1}
                className="mt-0.5 h-4 w-4 rounded border-line accent-brand"
              />
              I confirm I am 18 or older. Personal accounts are for adult learners.
            </label>
            {fieldErrors.adultConfirmed && <p className="mt-1 text-xs font-medium text-bad">{fieldErrors.adultConfirmed}</p>}
          </div>
        )}

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

        {isCompany ? (
          <p className="pt-1 text-center text-xs leading-5 text-muted">
            Company workspaces are created with a work email. Google sign-up creates a personal learner account.
          </p>
        ) : (
          <OAuthButtons active={active} onError={setFormError} beforeStart={prepareOAuthSignup} />
        )}
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

/** SSO buttons for the providers enabled in NEXT_PUBLIC_AUTH_PROVIDERS; renders
 * nothing (not even the divider) when none are. */
function OAuthButtons({
  active,
  onError,
  beforeStart,
}: {
  active: boolean;
  onError: (message: string) => void;
  /** Return false to stop before redirecting (e.g. a required checkbox). */
  beforeStart?: () => boolean;
}) {
  const [pending, setPending] = useState<OAuthProvider | null>(null);
  if (ENABLED_OAUTH_PROVIDERS.length === 0) return null;

  async function start(provider: OAuthProvider) {
    onError("");
    if (beforeStart && !beforeStart()) return;
    setPending(provider);
    try {
      await signInWithOAuthProvider(provider);
      // The browser navigates away to the provider; nothing further here.
    } catch (err) {
      onError(err instanceof AuthError ? err.message : `Could not start ${OAUTH_PROVIDER_LABELS[provider]} sign-in.`);
      setPending(null);
    }
  }

  return (
    <>
      <div className="flex items-center gap-3 py-0.5">
        <div className="h-px flex-1 bg-line" />
        <span className="text-xs font-medium uppercase tracking-wide text-muted">or continue with</span>
        <div className="h-px flex-1 bg-line" />
      </div>

      <div className={`grid gap-3 ${ENABLED_OAUTH_PROVIDERS.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
        {ENABLED_OAUTH_PROVIDERS.map((provider) => (
          <button
            key={provider}
            type="button"
            onClick={() => start(provider)}
            disabled={pending !== null}
            tabIndex={active ? 0 : -1}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-line bg-soft text-sm font-semibold text-ink transition-colors hover:bg-line/40 disabled:opacity-60"
          >
            {provider === "google" ? <GoogleIcon /> : <MicrosoftIcon />}
            {pending === provider ? "Redirecting..." : OAUTH_PROVIDER_LABELS[provider]}
          </button>
        ))}
      </div>
    </>
  );
}

function MicrosoftIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#F25022" d="M1 1h10.5v10.5H1z" />
      <path fill="#7FBA00" d="M12.5 1H23v10.5H12.5z" />
      <path fill="#00A4EF" d="M1 12.5h10.5V23H1z" />
      <path fill="#FFB900" d="M12.5 12.5H23V23H12.5z" />
    </svg>
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
