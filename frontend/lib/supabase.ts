import { createBrowserClient } from "@supabase/ssr";

const PLACEHOLDER_URL = "https://placeholder.supabase.co";
const PLACEHOLDER_ANON_KEY = "placeholder-anon-key";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** True for a value that could be a real configuration token: non-empty and
 * not a .env.example template (a URL/key containing "<...>", e.g.
 * "https://<project-ref>.supabase.co"). A malformed value is just as useless
 * as a missing one — createBrowserClient throws on a "<...>" URL, so it must
 * never be passed through. */
function isUsable(value: string | undefined): value is string {
  return Boolean(value && !value.includes("<") && !value.includes(">"));
}

// createBrowserClient throws synchronously on empty strings, which would
// crash module evaluation for every page that imports lib/api.ts (nearly all
// of them) — including during `next build`'s static prerendering, long before
// any code actually tries to sign in. Falling back to an obviously-fake
// placeholder keeps the app buildable/runnable with auth simply failing at
// the point of use until real values are set in frontend/.env (see
// frontend/.env.example). Unless BOTH values are usable, fall back to both
// placeholders — one-half-configured client is worse than a clear failure.
const configured =
  isUsable(SUPABASE_URL) &&
  isUsable(SUPABASE_ANON_KEY) &&
  SUPABASE_URL !== PLACEHOLDER_URL &&
  SUPABASE_ANON_KEY !== PLACEHOLDER_ANON_KEY;

if (!configured) {
  console.warn(
    "NEXT_PUBLIC_SUPABASE_URL/NEXT_PUBLIC_SUPABASE_ANON_KEY are not set — " +
      "sign-in/sign-up will not work until frontend/.env.local is configured."
  );
}

export const supabase = createBrowserClient(
  configured ? SUPABASE_URL : PLACEHOLDER_URL,
  configured ? SUPABASE_ANON_KEY : PLACEHOLDER_ANON_KEY
);

/** True only when a real Supabase project has been configured. A missing
 * env value falls through to the placeholders above, and calling auth under
 * those produces a confusing network error far from the real cause — every
 * caller crossing a Supabase Auth boundary should check this first and fail
 * with the actionable message instead. */
export function isSupabaseConfigured(): boolean {
  return configured;
}
