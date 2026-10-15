import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// /auth/accept-invite is public because the invite session arrives in the URL
// fragment, which the server never sees; the page establishes it client-side.
const PUBLIC_PATHS = [
  "/login", "/signup", "/auth/callback", "/auth/forgot-password", "/auth/reset-password", "/auth/accept-invite",
];
const REDIRECT_IF_AUTHED_PATHS = ["/login", "/signup"];
const MFA_PATH = "/auth/mfa";

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });

  // Same placeholder fallback as lib/supabase.ts — createServerClient throws
  // synchronously on empty or malformed ("<...>") URLs, which would otherwise
  // crash every request before frontend/.env is configured. Unless BOTH
  // values are usable real values, fall back to both placeholders.
  const rawUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const rawKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const usable = (v: string | undefined): v is string =>
    Boolean(v && !v.includes("<") && !v.includes(">"));
  const configured = usable(rawUrl) && usable(rawKey);
  const supabase = createServerClient(
    configured ? rawUrl : "https://placeholder.supabase.co",
    configured ? rawKey : "placeholder-anon-key",
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        },
      },
    }
  );

  // getUser() (not getSession()) — it revalidates against Supabase rather
  // than trusting the possibly-stale cookie payload, refreshing the
  // session cookie here if the access token had expired.
  // getClaims() verifies the session JWT's signature locally against the
  // project's published signing keys (cached for the process), so it is as
  // trustworthy as getUser() for this gate without a round trip to Supabase
  // Auth on every navigation — that call added ~0.3-0.5s to every page click.
  // It still refreshes an expired session (and rewrites the cookies) first.
  const { data: claimsData } = await supabase.auth.getClaims();
  const user = claimsData?.claims?.sub ? claimsData.claims : null;

  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.includes(pathname);

  if (!user && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (user && REDIRECT_IF_AUTHED_PATHS.includes(pathname)) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  // Two-step verification: an account with a verified authenticator app must
  // complete the challenge (aal1 → aal2) before reaching any app page. The
  // backend enforces aal2 independently for privileged actions; this keeps
  // the half-signed-in session out of the UI altogether.
  if (user && !isPublic) {
    const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    const challengePending = aal?.nextLevel === "aal2" && aal.currentLevel !== "aal2";
    if (challengePending && pathname !== MFA_PATH) {
      return NextResponse.redirect(new URL(MFA_PATH, request.url));
    }
    if (!challengePending && pathname === MFA_PATH) {
      return NextResponse.redirect(new URL("/", request.url));
    }
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
