import { isSupabaseConfigured, supabase } from "@/lib/supabase";
import { ApiError, provisionProfile } from "@/lib/api";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// >=8 chars, at least one uppercase, one lowercase, one digit.
const PASSWORD_RE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;

// Restrict sign-up to specific email domains, e.g. ["gmail.com"] or
// ["gmail.com", "zoikogroup.com"]. Leave empty to allow any domain.
const ALLOWED_EMAIL_DOMAINS: string[] = [];

export type SignUpFields = {
  firstName: string;
  lastName: string;
  email: string;
  companyName: string;
  password: string;
};

export type FieldErrors = Partial<Record<keyof SignUpFields, string>>;

export function validateSignUp(fields: SignUpFields): FieldErrors {
  const errors: FieldErrors = {};
  if (!fields.firstName.trim()) errors.firstName = "First name is required.";
  if (!fields.lastName.trim()) errors.lastName = "Last name is required.";
  if (!fields.companyName.trim()) errors.companyName = "Company name is required.";
  if (!fields.email.trim()) {
    errors.email = "Work email is required.";
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
      data: {
        first_name: fields.firstName,
        last_name: fields.lastName,
        company_name: fields.companyName,
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
 * into app_metadata. */
export async function signInWithPassword(email: string, password: string): Promise<void> {
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

  try {
    await provisionAndRefresh(data.session.access_token, data.user.user_metadata ?? {});
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
}

export async function signInWithGoogle(): Promise<void> {
  if (!isSupabaseConfigured()) {
    throw new AuthError(
      "Google sign-in is unavailable — Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL " +
        "and NEXT_PUBLIC_SUPABASE_ANON_KEY in frontend/.env and restart the dev server."
    );
  }
  const { error, data } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
  if (error) {
    throw new AuthError(`Could not start Google sign-in: ${error.message}`);
  }
  // When signInWithOAuth finishes without navigating (e.g. the SDK falls back
  // to returning a URL), hand the URL to the browser explicitly so the OAuth
  // redirect actually starts instead of leaving the button on "Redirecting...".
  if (!error && data?.url) {
    window.location.assign(data.url);
  }
}

/** Called from the /auth/callback page after an OAuth redirect completes.
 * Google sign-in has no email-verification gate, so this is the only
 * provisioning point for that path. */
export async function provisionAndRefresh(accessToken: string, metadata: Record<string, unknown>): Promise<void> {
  await provisionProfile(accessToken, {
    first_name: typeof metadata.first_name === "string" ? metadata.first_name : (typeof metadata.given_name === "string" ? metadata.given_name : ""),
    last_name: typeof metadata.last_name === "string" ? metadata.last_name : (typeof metadata.family_name === "string" ? metadata.family_name : ""),
    company_name: typeof metadata.company_name === "string" ? metadata.company_name : "",
  });
  // The token used above pre-dates /auth/provision writing app_metadata —
  // refresh so the next backend call already carries tenant_id/role.
  await supabase.auth.refreshSession();
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
