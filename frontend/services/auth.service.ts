import { isSupabaseConfigured, supabase } from "@/lib/supabase";
import { primeProfile } from "@/lib/profile-cache";
import { ApiError, provisionProfile, recordMfaEnrolled, type UserPublic } from "@/lib/api";
import { signInHomeFor } from "@/lib/roles";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// >=8 chars, at least one uppercase, one lowercase, one digit.
const PASSWORD_RE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;

// Restrict sign-up to specific email domains, e.g. ["gmail.com"] or
// ["gmail.com", "zoikogroup.com"]. Leave empty to allow any domain.
const ALLOWED_EMAIL_DOMAINS: string[] = [];

/** "individual": a private workspace for one person, who becomes a Learner.
 * "company": a company workspace whose first user is the Admin. */
export type AccountType = "individual" | "company";

export type SignUpFields = {
  accountType: AccountType;
  firstName: string;
  lastName: string;
  email: string;
  companyName: string;
  password: string;
  /** Individuals only: under-18 learners need guardian-consent controls that
   * don't exist yet, so individual accounts are adults only for now. */
  adultConfirmed: boolean;
};

export type FieldErrors = Partial<Record<keyof SignUpFields, string>>;

export const ADULT_ONLY_MESSAGE = "Please confirm you are 18 or older to create a personal account.";

export function validateSignUp(fields: SignUpFields): FieldErrors {
  const errors: FieldErrors = {};
  const isCompany = fields.accountType === "company";
  if (!fields.firstName.trim()) errors.firstName = "First name is required.";
  if (!fields.lastName.trim()) errors.lastName = "Last name is required.";
  if (isCompany && !fields.companyName.trim()) errors.companyName = "Company name is required.";
  if (!isCompany && !fields.adultConfirmed) errors.adultConfirmed = ADULT_ONLY_MESSAGE;
  if (!fields.email.trim()) {
    errors.email = isCompany ? "Work email is required." : "Email is required.";
  } else if (!EMAIL_RE.test(fields.email)) {
    errors.email = "Enter a valid email address.";
  } else if (ALLOWED_EMAIL_DOMAINS.length > 0) {
    const domain = fields.email.trim().split("@")[1]?.toLowerCase();
    if (!ALLOWED_EMAIL_DOMAINS.includes(domain)) {
      errors.email = `Only ${ALLOWED_EMAIL_DOMAINS.join(", ")} email addresses are allowed.`;
    }
  }
  if (!PASSWORD_RE.test(fields.password)) {
    errors.password = "Password must be at least 8 characters with an uppercase letter, a lowercase letter, and a number.";
  }
  return errors;
}

export class AuthError extends Error {}

/** Supabase's gateway rejects a publishable (anon) key that is wrong, rolled
 * or revoked with a bare "Invalid API key" (sb-error-code:
 * UNAUTHORIZED_INVALID_API_KEY) before GoTrue ever sees the request — every
 * email/password, sign-up and OAuth attempt fails identically no matter what
 * the credentials are. That is a deployment-configuration failure, not a
 * wrong password, so it gets its own actionable message instead of looking
 * like a user error. */
function publishableKeyRejected(message: string | undefined): boolean {
  return /invalid api key/i.test(message ?? "");
}

const PUBLISHABLE_KEY_FIX =
  "Sign-in is unavailable due to a server configuration problem: Supabase rejected this " +
  "deployment's publishable key. An administrator must replace NEXT_PUBLIC_SUPABASE_ANON_KEY " +
  "in frontend/.env with the current key from the Supabase Dashboard (Project Settings → " +
  "API Keys) and restart the dev server. Your password was not the issue.";

/** Supabase requires email verification before a session is issued (session
 * is null until the link is clicked, assuming "Confirm email" is enabled on
 * the project) — first_name/last_name/company_name are stashed in
 * user_metadata via signUp's `options.data` so they survive to the first
 * real sign-in, where they get handed to the backend's /auth/provision. */
export async function signUp(fields: SignUpFields): Promise<{ home: string | null }> {
  if (!isSupabaseConfigured()) {
    throw new AuthError(
      "Signup is unavailable — Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL " +
        "and NEXT_PUBLIC_SUPABASE_ANON_KEY in frontend/.env and restart the dev server."
    );
  }
  const { data, error } = await supabase.auth.signUp({
    email: fields.email,
    password: fields.password,
    options: {
      // The confirmation link signs the person in and provisions the
      // workspace there (company → Admin, individual → Learner).
      emailRedirectTo: `${window.location.origin}/auth/callback`,
      // Survives email verification, then reaches /auth/provision on the
      // first sign-in (provisionAndRefresh).
      data: {
        first_name: fields.firstName,
        last_name: fields.lastName,
        company_name: fields.accountType === "company" ? fields.companyName : "",
        account_type: fields.accountType,
        adult_confirmed: fields.accountType === "individual" && fields.adultConfirmed,
      },
    },
  });
  if (error) {
    if (publishableKeyRejected(error.message)) {
      throw new AuthError(PUBLISHABLE_KEY_FIX);
    }
    const code = error.code?.toLowerCase() ?? "";
    const message = error.message ?? "";
    if (
      code.includes("already") ||
      code.includes("exists") ||
      message.toLowerCase().includes("already registered") ||
      message.toLowerCase().includes("already exists")
    ) {
      throw new AuthError("An account with this email already exists.");
    }
    // Surface the real Supabase error (verification is handled separately
    // above) — a "network request failed" here means the Supabase URL/key is
    // wrong or the project is unreachable, and masking that behind a generic
    // message is exactly what made this failure look like a signup bug.
    throw new AuthError(`Signup failed: ${message}`);
  }
  // An address that is already registered gets no error from Supabase (so
  // sign-up can't be used to probe for accounts): it returns a user with no
  // identities and sends no email. Say so instead of "check your email".
  if (data.user && (data.user.identities?.length ?? 0) === 0) {
    throw new AuthError("An account with this email already exists. Sign in, or use Forgot password.");
  }
  // "Confirm email" switched off on the Supabase project: the session exists
  // already, so provision now and go straight in.
  if (data.session) {
    const profile = await provisionAndRefresh(data.session.access_token, data.user?.user_metadata ?? {});
    return { home: signInHomeFor(profile) };
  }
  return { home: null };
}

export class EmailNotConfirmedError extends AuthError {}

/** Sends the sign-up confirmation email again. */
export async function resendConfirmation(email: string): Promise<void> {
  const { error } = await supabase.auth.resend({
    type: "signup",
    email,
    options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
  });
  if (error) {
    if (error.status === 429 || /rate limit|security purposes/i.test(error.message)) {
      throw new AuthError("A verification email was sent recently. Please wait a minute and try again.");
    }
    throw new AuthError(`Could not resend the verification email: ${error.message}`);
  }
}

/** On success, provisions the local backend profile (idempotent — a no-op
 * after the first successful login) and refreshes the session so the very
 * next backend call carries the tenant_id/role /auth/provision just wrote
 * into app_metadata. Resolves with whether the account still owes an MFA
 * challenge — the caller then routes to /auth/mfa instead of the app. */
export async function signInWithPassword(
  email: string,
  password: string,
): Promise<{ mfaRequired: boolean; home: string }> {
  if (!isSupabaseConfigured()) {
    throw new AuthError(
      "Sign-in is unavailable — Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL " +
        "and NEXT_PUBLIC_SUPABASE_ANON_KEY in frontend/.env and restart the dev server."
    );
  }
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });

  if (error) {
    // The gateway rejected the API key itself — nothing about the email or
    // password was even evaluated. Report the configuration problem instead
    // of a misleading credential error.
    if (publishableKeyRejected(error.message)) {
      throw new AuthError(PUBLISHABLE_KEY_FIX);
    }
    // With "Confirm email" on, Supabase refuses an unverified account with
    // its own code — reporting that as a wrong password sent people round in
    // circles resetting a password that was never the problem.
    if (error.code === "email_not_confirmed" || /email not confirmed/i.test(error.message)) {
      throw new EmailNotConfirmedError("Please verify your email before signing in. Check your inbox for the confirmation link.");
    }
    if (error.status === 429) {
      throw new AuthError("Too many sign-in attempts. Please wait a minute and try again.");
    }
    if (error.code === "invalid_credentials" || error.status === 400) {
      throw new AuthError("Incorrect email or password.");
    }
    throw new AuthError(`Sign-in failed: ${error.message}`);
  }

  if (!data.user.email_confirmed_at) {
    await supabase.auth.signOut();
    throw new EmailNotConfirmedError("Please verify your email before signing in. Check your inbox for the confirmation link.");
  }

  if (!data.session) {
    throw new AuthError("Sign-in did not create a session. Please try again.");
  }

  let profile: UserPublic;
  try {
    profile = await provisionAndRefresh(data.session.access_token, data.user.user_metadata ?? {});
  } catch (err) {
    // Provisioning fails for two very different reasons, and the UI must not
    // squash them into one:
    //   - transport/5xx     → the backend itself is unreachable (was down,
    //                         wrong port, restarting) — say so explicitly.
    //   - 401/403 from the  → the claiming token was rejected (session
    //     backend              invalid/expired, or the project's Supabase
    //                         signing keys changed mid-session).
    // ApiError keeps the HTTP status; a raw TypeError means fetch never got a
    // response at all. Everything maps to an AuthError so the caller surfaces
    // the true cause instead of its "could not reach the server" fallback.
    if (err instanceof ApiError) {
      if (err.status === 0 || err.status >= 500) {
        throw new AuthError(
          "The ZoikoLogia backend could not be reached. Make sure it is running on port 8010, then sign in again.",
        );
      }
      if (err.status === 403 || err.status === 409 || err.status === 422) {
        // The server refused this account (invite-only deployment, an email
        // already owned by a different sign-in identity, an unconfirmed age):
        // its own message says what to do, and the half-signed-in session
        // must not linger — left behind, it loops on 401s from /auth/me.
        await supabase.auth.signOut();
        throw new AuthError(err.message);
      }
      await supabase.auth.signOut();
      throw new AuthError(
        err.status === 401
          ? "Your session could not be validated by the server. Please sign in again."
          : "Sign-in could not be completed on the server. Please try again later.",
      );
    }
    if (err instanceof TypeError) {
      throw new AuthError(
        "The ZoikoLogia backend could not be reached. Make sure it is running on port 8010, then sign in again.",
      );
    }
    throw err;
  }
  return { mfaRequired: await mfaChallengeRequired(), home: signInHomeFor(profile) };
}

// ── Single sign-on ──────────────────────────────────────────────────────────

export type OAuthProvider = "google" | "azure";

export const OAUTH_PROVIDER_LABELS: Record<OAuthProvider, string> = {
  google: "Google",
  azure: "Microsoft",
};

/** SSO providers shown on the sign-in card, from NEXT_PUBLIC_AUTH_PROVIDERS
 * (comma-separated: "google,azure"). Each must also be enabled in the
 * Supabase project's Auth → Providers. Defaults to Google, the provider this
 * app shipped with. */
export const ENABLED_OAUTH_PROVIDERS: OAuthProvider[] = (process.env.NEXT_PUBLIC_AUTH_PROVIDERS ?? "google")
  .split(",")
  .map((p) => p.trim().toLowerCase())
  .filter((p): p is OAuthProvider => p in OAUTH_PROVIDER_LABELS);

/** False when NEXT_PUBLIC_ALLOW_SIGNUP=false: the deployment is invite-only
 * (pair with the backend's ALLOW_PUBLIC_SIGNUP=false, which is the actual
 * control — this only hides the form). */
export const PUBLIC_SIGNUP_ENABLED = process.env.NEXT_PUBLIC_ALLOW_SIGNUP !== "false";

export async function signInWithOAuthProvider(provider: OAuthProvider): Promise<void> {
  const label = OAUTH_PROVIDER_LABELS[provider];
  if (!isSupabaseConfigured()) {
    throw new AuthError(
      `${label} sign-in is unavailable — Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL ` +
        "and NEXT_PUBLIC_SUPABASE_ANON_KEY in frontend/.env and restart the dev server."
    );
  }
  const { error, data } = await supabase.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: `${window.location.origin}/auth/callback`,
      // Microsoft Entra ID only returns the email claim when asked for it.
      ...(provider === "azure" ? { scopes: "email" } : {}),
    },
  });
  if (error) {
    if (publishableKeyRejected(error.message)) {
      throw new AuthError(PUBLISHABLE_KEY_FIX);
    }
    throw new AuthError(`Could not start ${label} sign-in: ${error.message}`);
  }
  // When signInWithOAuth finishes without navigating (e.g. the SDK falls back
  // to returning a URL), hand the URL to the browser explicitly so the OAuth
  // redirect actually starts instead of leaving the button on "Redirecting...".
  if (!error && data?.url) {
    window.location.assign(data.url);
  }
}

// OAuth sign-up can't carry form data through the provider redirect, so the
// adult confirmation given on the sign-up card waits here until
// /auth/callback provisions the account. Per tab; consumed once. (The
// account type it carries is no longer used: OAuth is always a Learner.)
const PENDING_SIGNUP_KEY = "zoiko_pending_signup";

type SignupChoice = { accountType: AccountType; adultConfirmed: boolean };

export function rememberSignupChoice(choice: SignupChoice): void {
  try {
    sessionStorage.setItem(PENDING_SIGNUP_KEY, JSON.stringify(choice));
  } catch {
    // Storage unavailable: the account is provisioned with the default type.
  }
}

function takeSignupChoice(): SignupChoice | null {
  try {
    const raw = sessionStorage.getItem(PENDING_SIGNUP_KEY);
    sessionStorage.removeItem(PENDING_SIGNUP_KEY);
    return raw ? (JSON.parse(raw) as SignupChoice) : null;
  } catch {
    return null;
  }
}

/** Whether the access token's app_metadata already names this profile's
 * tenant and role. Reads the payload only — the backend verifies the token. */
function tokenMatchesProfile(accessToken: string, profile: UserPublic): boolean {
  try {
    const part = accessToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), "=")));
    const meta = payload?.app_metadata ?? {};
    return meta.tenant_id === profile.tenant_id && meta.role === profile.role;
  } catch {
    return false;
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Provisions the backend profile (idempotent: only the first call creates
 * anything) and refreshes the session so the next call carries tenant/role.
 * Used after password sign-in, OAuth (/auth/callback) and invitations. A
 * company workspace, whose creator becomes its Admin, is only ever created by
 * an email sign-up that chose "My company" (its metadata says so); Google /
 * Microsoft sign-in is always an individual Learner account. */
export async function provisionAndRefresh(
  accessToken: string,
  metadata: Record<string, unknown>,
  confirm: { adultConfirmed?: boolean } = {},
): Promise<UserPublic> {
  const pending = takeSignupChoice();
  const [fullFirst, ...fullRest] = text(metadata.full_name || metadata.name).split(" ");
  // Only an email sign-up that chose "My company" carries account_type in its
  // metadata. Google / Microsoft sign-in is always a personal Learner account
  // (the backend enforces this from the token's provider too).
  const accountType: AccountType = metadata.account_type === "company" ? "company" : "individual";
  const profile = await provisionProfile(accessToken, {
    first_name: text(metadata.first_name) || text(metadata.given_name) || fullFirst,
    last_name: text(metadata.last_name) || text(metadata.family_name) || fullRest.join(" "),
    company_name: text(metadata.company_name),
    account_type: accountType,
    adult_confirmed: confirm.adultConfirmed ?? pending?.adultConfirmed ?? metadata.adult_confirmed === true,
  });
  // A first sign-in's token pre-dates /auth/provision writing app_metadata —
  // refresh so the next backend call carries tenant_id/role. Every later
  // sign-in already has them, and the refresh was a wasted round trip.
  if (!tokenMatchesProfile(accessToken, profile)) {
    await supabase.auth.refreshSession();
  }
  primeProfile(profile);
  return profile;
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut();
}

/** Password reset is owned entirely by Supabase's SDK: this sends the reset
 * email through Supabase's own mailer (user clicks the link, lands on
 * /auth/reset-password), and
 * updatePassword() below finalizes it with the session the link created.
 * No backend endpoint — the backend has nothing to add to a flow Supabase
 * already verifies end-to-end against its own token. */
export async function resetPassword(email: string): Promise<void> {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/auth/reset-password`,
  });
  if (error) {
    // Supabase's built-in mailer allows only a few emails an hour for the
    // whole project; say so instead of a generic failure.
    if (error.status === 429 || /rate limit|security purposes/i.test(error.message)) {
      throw new AuthError(
        "Too many reset emails have been sent recently. Please wait a few minutes and try again, or use the last reset link you received.",
      );
    }
    throw new AuthError("Could not send a reset link. Please try again.");
  }
}

export async function updatePassword(newPassword: string): Promise<void> {
  if (!PASSWORD_RE.test(newPassword)) {
    throw new AuthError("Password must be at least 8 characters with an uppercase letter, a lowercase letter, and a number.");
  }
  const { error } = await supabase.auth.updateUser({ password: newPassword });
  if (error) {
    if (error.code === "same_password") {
      throw new AuthError("Your new password must be different from your current one.");
    }
    if (error.code === "weak_password") {
      throw new AuthError(`That password is too weak: ${error.message}`);
    }
    if (error.status === 401 || error.code === "session_not_found" || error.code === "session_expired") {
      throw new AuthError("Your reset link has expired. Request a new one.");
    }
    throw new AuthError("Could not update your password. Please try again.");
  }
}

// ── Multi-factor authentication (TOTP) ─────────────────────────────────────
// Enrolment and challenges run entirely through Supabase Auth; a verified
// challenge raises the session to aal2, which the backend reads from the
// token for its step-up checks.

/** True when the account has a verified factor but this session has not
 * completed a challenge yet. */
export async function mfaChallengeRequired(): Promise<boolean> {
  const { data, error } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
  if (error || !data) return false;
  return data.nextLevel === "aal2" && data.currentLevel !== "aal2";
}

export type TotpFactor = { id: string; friendlyName: string; status: string };

export async function listTotpFactors(): Promise<TotpFactor[]> {
  const { data, error } = await supabase.auth.mfa.listFactors();
  if (error) throw new AuthError("Could not load your authenticator apps.");
  return data.all
    .filter((f) => f.factor_type === "totp")
    .map((f) => ({ id: f.id, friendlyName: f.friendly_name ?? "Authenticator app", status: f.status }));
}

export type TotpEnrollment = { factorId: string; qrCode: string; secret: string };

/** Starts enrolment. Any abandoned unverified factor is removed first, since
 * Supabase refuses a second factor with the same friendly name. */
export async function startTotpEnrollment(): Promise<TotpEnrollment> {
  const existing = await listTotpFactors();
  for (const factor of existing.filter((f) => f.status !== "verified")) {
    await supabase.auth.mfa.unenroll({ factorId: factor.id });
  }
  const { data, error } = await supabase.auth.mfa.enroll({
    factorType: "totp",
    friendlyName: `Authenticator ${new Date().toISOString().slice(0, 10)}`,
  });
  if (error || !data) throw new AuthError(`Could not start MFA enrolment${error ? `: ${error.message}` : "."}`);
  return { factorId: data.id, qrCode: data.totp.qr_code, secret: data.totp.secret };
}

async function verifyFactor(factorId: string, code: string): Promise<void> {
  const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId, code: code.trim() });
  if (error) throw new AuthError("That code is not valid. Check your authenticator app and try again.");
}

/** Completes enrolment, then records it in the audit ledger (best effort —
 * the factor is already active even if the audit call fails). */
export async function confirmTotpEnrollment(factorId: string, code: string): Promise<void> {
  await verifyFactor(factorId, code);
  const { data } = await supabase.auth.getSession();
  if (data.session) {
    await recordMfaEnrolled(data.session.access_token).catch(() => undefined);
  }
}

/** Sign-in challenge against the account's verified TOTP factor. */
export async function verifyTotpSignIn(code: string): Promise<void> {
  const factor = (await listTotpFactors()).find((f) => f.status === "verified");
  if (!factor) throw new AuthError("No authenticator app is set up for this account.");
  await verifyFactor(factor.id, code);
}

export async function removeTotpFactor(factorId: string): Promise<void> {
  const { error } = await supabase.auth.mfa.unenroll({ factorId });
  if (error) throw new AuthError(`Could not remove the authenticator app: ${error.message}`);
}
