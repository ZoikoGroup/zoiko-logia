"use client";

import { FormEvent, ReactNode, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Building2,
  ChevronRight,
  Eye,
  EyeOff,
  GraduationCap,
  LockKeyhole,
  Mail,
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

type Mode = "signin" | "signup";

// The ZoikoLogia sign-in template (28 Oct 2026): its logo, hero panel and
// colours. The hero is the template's own artwork, shown unchanged.
export function AuthCard({ initialMode }: { initialMode: Mode }) {
  // Invite-only deployments never show the sign-up form, even at /signup.
  const [mode, setMode] = useState<Mode>(PUBLIC_SIGNUP_ENABLED ? initialMode : "signin");

  return (
    <AuthShell tab={mode} onSelect={setMode}>
      <SignInPanel
        active={mode === "signin"}
        onSwitchToSignup={PUBLIC_SIGNUP_ENABLED ? () => setMode("signup") : undefined}
      />
      {PUBLIC_SIGNUP_ENABLED && (
        <SignUpPanel active={mode === "signup"} onSwitchToSignin={() => setMode("signin")} />
      )}
    </AuthShell>
  );
}

/** The template's page: artwork on the left, the card with its Login /
 * Register / Reset Password tabs and footer on the right. Login and Register
 * switch in place through onSelect when given; otherwise they open their pages. */
export function AuthShell({ tab, onSelect, children }: {
  tab: Mode | "reset";
  onSelect?: (mode: Mode) => void;
  children: ReactNode;
}) {
  const router = useRouter();
  const select = (mode: Mode) => (onSelect ? onSelect(mode) : router.push(mode === "signin" ? "/login" : "/signup"));

  return (
    <main className="auth-light min-h-screen w-full bg-[#F7F8FA] text-[#111827]">
      <div className="flex min-h-screen lg:h-screen">
        {/* Full height at the artwork's own 868x1024 shape, as in the template, so it is never cropped or enlarged. */}
        <section className="relative hidden h-screen max-w-[62vw] shrink-0 overflow-hidden bg-[#001030] lg:block" style={{ aspectRatio: "868 / 1024" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/brand/login-hero.jpg"
            alt="ZoikoLogia: intelligent accounting and finance, for a stronger tomorrow."
            className="absolute inset-0 h-full w-full object-cover object-left-top"
          />
        </section>

        <section className="relative flex min-h-screen min-w-0 flex-1 items-center justify-center overflow-y-auto px-4 py-6 lg:min-h-0">
          {/* The template's orange and navy diagonal accents behind the card. */}
          <div className="pointer-events-none absolute -right-24 top-[-10%] h-[40%] w-40 rotate-[28deg] bg-gradient-to-b from-[#F57A14]/70 to-[#F57A14]/0" />
          <div className="pointer-events-none absolute -bottom-24 -right-16 h-56 w-32 rotate-[28deg] bg-gradient-to-t from-[#0B2A5B]/80 to-[#F57A14]/60" />
          <div className="relative w-full max-w-md">
            <div className="relative overflow-hidden rounded-2xl bg-white shadow-[0_18px_50px_rgba(11,21,51,0.12)]">
              <nav className="grid grid-cols-3 border-b border-[#EEF0F4] text-center text-sm" aria-label="Account">
                <TemplateTab active={tab === "signin"} onClick={() => select("signin")}>Login</TemplateTab>
                <TemplateTab
                  active={tab === "signup"}
                  onClick={() => select("signup")}
                  disabled={!PUBLIC_SIGNUP_ENABLED}
                  title={PUBLIC_SIGNUP_ENABLED ? undefined : "Access is by invitation"}
                >
                  Register
                </TemplateTab>
                <TemplateTab active={tab === "reset"} onClick={() => router.push("/auth/forgot-password")}>
                  Reset Password
                </TemplateTab>
              </nav>
              <div className="relative grid">{children}</div>
              <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-[#EEF0F4] px-5 py-2.5 text-[11px] text-[#9098A8]">
                <span className="flex flex-wrap items-center gap-2">
                  {["Privacy", "Terms", "Accessibility", "Help"].map((item, index) => (
                    <span key={item} className="flex items-center gap-2">
                      {index > 0 && <span aria-hidden="true">•</span>}
                      <button type="button" title="Coming soon" className="hover:text-[#5A6278]">{item}</button>
                    </span>
                  ))}
                </span>
                <span>© 2026 Zoiko Tech Inc.</span>
              </footer>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function TemplateTab({ active, onClick, disabled, title, children }: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-current={active ? "page" : undefined}
      className={`relative py-3 font-semibold text-[#0B1533] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${active ? "" : "opacity-80 hover:opacity-100"}`}
    >
      {children}
      {active && <span className="absolute inset-x-6 bottom-0 h-[3px] rounded-full bg-[#F57A14]" />}
    </button>
  );
}

export function TemplateLogo() {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/brand/zoikologia-logo.png" alt="ZoikoLogia" width={393} height={69} className="mx-auto h-auto w-[190px] max-w-full" />
  );
}

function panelClassName(active: boolean, direction: "left" | "right") {
  const hiddenTransform = direction === "left" ? "-translate-x-full" : "translate-x-full";
  return [
    "col-start-1 row-start-1 w-full p-5 sm:p-6",
    "transition-all duration-300 ease-out",
    // The hidden panel is taken out of the flow so the card is only as tall as the shown one.
    active ? "translate-x-0 opacity-100" : `absolute inset-x-0 top-0 ${hiddenTransform} opacity-0 pointer-events-none`,
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
      <div className="mb-3 text-center">
        <TemplateLogo />
        <h2 className="mt-3 text-2xl font-extrabold leading-tight tracking-tight text-[#0B1533]">Welcome back!</h2>
        <p className="mt-0.5 text-sm text-[#5A6278]">Sign in to your ZoikoLogia account.</p>
      </div>

      <TemplateSsoButtons active={active} onError={setError} />

      <div className="my-3 flex items-center gap-3">
        <div className="h-px flex-1 bg-[#E3E6EC]" />
        <span className="text-xs text-[#5A6278]">or sign in with email</span>
        <div className="h-px flex-1 bg-[#E3E6EC]" />
      </div>

      <form onSubmit={handleSubmit} className="space-y-2.5">
        <div>
          <label htmlFor="signin-email" className="mb-1 block text-xs font-medium text-[#111827]">
            Work email address
          </label>
          <div className="relative">
            <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#5A6278]" />
            <input
              id="signin-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
              autoComplete="email"
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-[#E3E6EC] bg-white pl-10 pr-3 text-sm text-[#111827] placeholder:text-[#A0A8B0] outline-none focus:border-[#F57A14] focus:ring-2 focus:ring-[#F57A14]/20"
            />
          </div>
        </div>
        <div>
          <label htmlFor="signin-password" className="mb-1 block text-xs font-medium text-[#111827]">Password</label>
          <div className="relative">
            <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#5A6278]" />
            <input
              id="signin-password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
              tabIndex={active ? 0 : -1}
              className="h-9 w-full rounded-lg border border-[#E3E6EC] bg-white pl-10 pr-10 text-sm text-[#111827] placeholder:text-[#A0A8B0] outline-none focus:border-[#F57A14] focus:ring-2 focus:ring-[#F57A14]/20"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              tabIndex={active ? 0 : -1}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[#0B2A5B] hover:text-[#0B1533]"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-xs text-[#111827]">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              tabIndex={active ? 0 : -1}
              className="h-4 w-4 rounded border-[#E3E6EC] accent-[#F57A14]"
            />
            Remember me for 30 days
          </label>
          <button
            type="button"
            onClick={() => router.push("/auth/forgot-password")}
            tabIndex={active ? 0 : -1}
            className="text-xs font-semibold text-[#F57A14] hover:underline"
          >
            Forgot password?
          </button>
        </div>

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
          className="inline-flex h-10 w-full items-center justify-center rounded-lg bg-[#F57A14] px-4 text-sm font-bold text-white shadow-[0_10px_24px_rgba(245,122,20,0.25)] transition-colors hover:bg-[#DD6A0C] disabled:opacity-60"
        >
          {submitting ? "Signing in..." : "Log In"}
        </button>
      </form>

      {onSwitchToSignup ? (
        <p className="mt-3 text-center text-sm text-[#5A6278]">
          New to ZoikoLogia?{" "}
          <button
            type="button"
            onClick={onSwitchToSignup}
            tabIndex={active ? 0 : -1}
            className="ml-1 font-bold text-[#F57A14] hover:underline"
          >
            Register
          </button>
        </p>
      ) : (
        <p className="mt-3 text-center text-xs text-[#5A6278]">
          Access is by invitation. Ask your administrator for an account.
        </p>
      )}
    </div>
  );
}

const TEMPLATE_SSO: { key: OAuthProvider | "apple" | "sso"; label: string }[] = [
  { key: "azure", label: "Microsoft" },
  { key: "google", label: "Google" },
  { key: "apple", label: "Apple" },
  { key: "sso", label: "Company SSO" },
];

/** The template's four sign-in rows. Microsoft and Google start the real
 * sign-in when enabled in NEXT_PUBLIC_AUTH_PROVIDERS; a provider that is not
 * set up (Apple and Company SSO have no integration yet) says so rather than
 * pretending to work. */
function TemplateSsoButtons({ active, onError }: { active: boolean; onError: (message: string) => void }) {
  const [pending, setPending] = useState<string | null>(null);

  async function start(key: OAuthProvider | "apple" | "sso", label: string) {
    onError("");
    const provider = ENABLED_OAUTH_PROVIDERS.find((enabled) => enabled === key);
    if (!provider) {
      onError(`${label} sign-in isn't set up for this workspace yet. Sign in with your work email.`);
      return;
    }
    setPending(provider);
    try {
      await signInWithOAuthProvider(provider);
      // The browser navigates away to the provider; nothing further here.
    } catch (err) {
      onError(err instanceof AuthError ? err.message : `Could not start ${label} sign-in.`);
      setPending(null);
    }
  }

  return (
    <div className="space-y-2">
      {TEMPLATE_SSO.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          onClick={() => start(key, label)}
          disabled={pending !== null}
          tabIndex={active ? 0 : -1}
          className="flex h-9 w-full items-center gap-3 rounded-lg border border-[#E3E6EC] bg-white px-4 text-left text-sm font-medium text-[#111827] transition-colors hover:border-[#F57A14]/50 hover:bg-[#FFF8F2] disabled:opacity-60"
        >
          <span className="flex w-5 justify-center">
            {key === "azure" ? <MicrosoftIcon size={16} /> : key === "google" ? <GoogleIcon size={16} />
              : key === "apple" ? <AppleIcon /> : <Building2 size={16} className="text-[#0B1533]" />}
          </span>
          <span className="flex-1">{pending === key ? "Redirecting..." : `Continue with ${label}`}</span>
          <ChevronRight size={16} className="text-[#0B1533]" />
        </button>
      ))}
    </div>
  );
}

function AppleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#000" d="M16.37 12.73c-.03-2.6 2.12-3.85 2.22-3.91-1.21-1.77-3.09-2.01-3.76-2.04-1.6-.16-3.12.94-3.93.94-.81 0-2.06-.92-3.39-.89-1.74.03-3.35 1.01-4.25 2.57-1.81 3.14-.46 7.79 1.3 10.34.86 1.25 1.89 2.65 3.24 2.6 1.3-.05 1.79-.84 3.36-.84 1.57 0 2.01.84 3.39.81 1.4-.02 2.29-1.27 3.14-2.53.99-1.45 1.4-2.86 1.42-2.93-.03-.01-2.72-1.04-2.74-4.12ZM13.78 5.09c.71-.87 1.2-2.07 1.06-3.27-1.03.04-2.28.69-3.02 1.55-.66.76-1.24 1.99-1.09 3.16 1.15.09 2.33-.58 3.05-1.44Z" />
    </svg>
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
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-[#F57A14] px-4 text-sm font-bold text-white shadow-[0_10px_24px_rgba(245,122,20,0.25)] transition-colors hover:bg-[#DD6A0C] disabled:opacity-60"
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

function MicrosoftIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#F25022" d="M1 1h10.5v10.5H1z" />
      <path fill="#7FBA00" d="M12.5 1H23v10.5H12.5z" />
      <path fill="#00A4EF" d="M1 12.5h10.5V23H1z" />
      <path fill="#FFB900" d="M12.5 12.5H23V23H12.5z" />
    </svg>
  );
}

function GoogleIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
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
