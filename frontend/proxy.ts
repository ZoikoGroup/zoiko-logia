import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const AUTH_COOKIE = "zoiko_auth";

export function proxy(request: NextRequest) {
  const isAuthed = Boolean(request.cookies.get(AUTH_COOKIE)?.value);
  if (!isAuthed) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
}

export const config = {
  matcher: ["/((?!login|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
