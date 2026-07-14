"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

const PUBLIC_PATHS = ["/login", "/signup", "/auth/callback"];

/** Defense in depth alongside proxy.ts: Next's own guidance is that
 * middleware/proxy alone isn't sufficient for full session enforcement
 * (it's meant for optimistic checks), so protected pages also verify
 * client-side and bounce to /login if the session drops out from under
 * them (e.g. expired refresh token). Skips the same public paths
 * AppChrome already skips its own chrome for. */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    if (!isPublic && !loading && !session) {
      router.replace("/login");
    }
  }, [isPublic, loading, session, router]);

  if (isPublic) {
    return <>{children}</>;
  }

  if (loading || !session) {
    return null;
  }

  return <>{children}</>;
}
