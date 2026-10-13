import { isSupabaseConfigured, supabase } from "@/lib/supabase";
import { ApiError, provisionProfile, recordMfaEnrolled, type UserPublic } from "@/lib/api";
import { homePathFor } from "@/lib/roles";

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

/** Supabase requires email verification before a session is issued (session
 * is null until the link is clicked, assuming "Confirm email" is enabled on
 * the project) — first_name/last_name/company_name are stashed in
 * user_metadata via signUp's `options.data` so they survive to the first
 * real sign-in, where they get handed to the backend's /auth/provision. */
export async function signUp(fields: SignUpFields): Promise<void> {
  if (!isSupabaseConfigured()) {
    throw new AuthError(
      "Signup is unavailable — Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL " +
        "and NEXT_PUBLIC_SUPABASE_ANON_KEY in frontend/.env and restart the dev server."
    );
  }
  const { error } = await supabase.auth.signUp({
    email: fields.email,
    password: fields.password,
    options: {
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
    throw new AuthError("Incorrect email or password.");
  }

  if (!data.user.email_confirmed_at) {
    await supabase.auth.signOut();
    throw new AuthError("Please verify your email before signing in.");
  }

  if (!data.session) {
    throw new AuthError("Sign-in did not create a session. Please try again.");
  }

  let role: string;
  try {
    role = (await provisionAndRefresh(data.session.access_token, data.user.user_metadata ?? {})).role;
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
      if (err.status === 403) {
        // Invite-only deployment refusing an unknown sign-up: the backend's
        // own message says what to do, and the half-signed-in session must
        // not linger.
        await supabase.auth.signOut();
        throw new AuthError(err.message);
      }
      throw new AuthError(
        err.status === 401 || err.status === 403
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
  return { mfaRequired: await mfaChallengeRequired(), home: homePathFor(role) };
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
// "Myself / My company" choice made on the sign-up card waits here until
// /auth/callback provisions the account. Per tab; consumed once.
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

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Provisions the backend profile (idempotent: only the first call creates
 * anything) and refreshes the session so the next call carries tenant/role.
 * Used after password sign-in, OAuth (/auth/callback) and invitations. The
 * workspace type comes from sign-up metadata (email sign-up) or the choice
 * remembered before an OAuth redirect; with neither, it stays "company",
 * the original behaviour. */
export async function provisionAndRefresh(
  accessToken: string,
  metadata: Record<string, unknown>,
): Promise<UserPublic> {
  const pending = takeSignupChoice();
  const [fullFirst, ...fullRest] = text(metadata.full_name || metadata.name).split(" ");
  const accountType: AccountType =
    pending?.accountType ?? (metadata.account_type === "individual" ? "individual" : "company");
  const profile = await provisionProfile(accessToken, {
    first_name: text(metadata.first_name) || text(metadata.given_name) || fullFirst,
    last_name: text(metadata.last_name) || text(metadata.family_name) || fullRest.join(" "),
    company_name: text(metadata.company_name),
    account_type: accountType,
    adult_confirmed: pending?.adultConfirmed ?? metadata.adult_confirmed === true,
  });
  // The token used above pre-dates /auth/provision writing app_metadata —
  // refresh so the next backend call already carries tenant_id/role.
  await supabase.auth.refreshSession();
  return profile;
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut();
}

/** Password reset is owned entirely by Supabase's SDK: this sends the reset
 * email (user clicks the link, lands on /auth/reset-password), and
 * updatePassword() below finalizes it with the session the link created.
 * No backend endpoint — the backend has nothing to add to a flow Supabase
 * already verifies end-to-end against its own token. */
export async function resetPassword(email: string): Promise<void> {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/auth/reset-password`,
  });
  if (error) throw new AuthError("Could not send a reset link. Please try again.");
}

export async function updatePassword(newPassword: string): Promise<void> {
  if (!PASSWORD_RE.test(newPassword)) {
    throw new AuthError("Password must be at least 8 characters with an uppercase letter, a lowercase letter, and a number.");
  }
  const { error } = await supabase.auth.updateUser({ password: newPassword });
  if (error) throw new AuthError("Could not update your password. Please try again.");
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
