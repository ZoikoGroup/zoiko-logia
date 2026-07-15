import { createBrowserClient } from "@supabase/ssr";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  // createBrowserClient throws synchronously on empty strings, which would
  // crash module evaluation for every page that imports lib/api.ts (nearly
  // all of them) — including during `next build`'s static prerendering,
  // long before any code actually tries to sign in. Falling back to an
  // obviously-fake placeholder keeps the app buildable/runnable with auth
  // simply failing at the point of use until real values are set in
  // frontend/.env.local (see frontend/.env.example).
  console.warn(
    "NEXT_PUBLIC_SUPABASE_URL/NEXT_PUBLIC_SUPABASE_ANON_KEY are not set — " +
      "sign-in/sign-up will not work until frontend/.env.local is configured."
  );
}

export const supabase = createBrowserClient(
  SUPABASE_URL || "https://placeholder.supabase.co",
  SUPABASE_ANON_KEY || "placeholder-anon-key"
);
