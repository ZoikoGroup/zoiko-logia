import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/signup", "/auth/callback", "/auth/forgot-password", "/auth/reset-password"];
const REDIRECT_IF_AUTHED_PATHS = ["/login", "/signup"];

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
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.includes(pathname);

  if (!user && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (user && REDIRECT_IF_AUTHED_PATHS.includes(pathname)) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
