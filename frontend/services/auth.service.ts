import { supabase } from "@/lib/supabase";
import { provisionProfile } from "@/lib/api";

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
    if (error.message.toLowerCase().includes("already registered") || error.message.toLowerCase().includes("already exists")) {
      throw new AuthError("An account with this email already exists.");
    }
    throw new AuthError("Could not create your account. Please try again.");
  }
}

/** On success, provisions the local backend profile (idempotent — a no-op
 * after the first successful login) and refreshes the session so the very
 * next backend call carries the tenant_id/role /auth/provision just wrote
 * into app_metadata. */
export async function signInWithPassword(email: string, password: string): Promise<void> {
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });

  if (error) {
    throw new AuthError("Incorrect email or password.");
  }

  if (!data.user.email_confirmed_at) {
    await supabase.auth.signOut();
    throw new AuthError("Please verify your email before signing in.");
  }

  await provisionAndRefresh(data.session.access_token, data.user.user_metadata ?? {});
}

export async function signInWithGoogle(): Promise<void> {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
  if (error) {
    throw new AuthError("Could not start Google sign-in. Please try again.");
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
