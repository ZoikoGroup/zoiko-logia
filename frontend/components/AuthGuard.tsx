"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

const PUBLIC_PATHS = [
  "/login", "/signup", "/auth/callback", "/auth/forgot-password", "/auth/reset-password", "/auth/accept-invite",
];

/** Defense in depth alongside proxy.ts: Next's own guidance is that
 * middleware/proxy alone isn't sufficient for full session enforcement
 * (it's meant for optimistic checks), so protected pages also verify
 * client-side and bounce to /login if the session drops out from under
 * them (e.g. expired refresh token). Skips the same public paths
 * AppChrome already skips its own chrome for. */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { session, loading, profile, profileLoading, profileError, refreshProfile, signOut } = useAuth();
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

  // A Supabase session alone does not establish access to a backend
  // workspace. Do not mount pages or notification polling after /auth/me
  // refuses it, or while the first profile verification is in flight.
  if (!profile && profileLoading) return null;
  if (!profile && profileError) {
    return (
      <main className="flex min-h-screen w-full items-center justify-center p-8">
        <div className="max-w-md space-y-4">
          <h1 className="text-xl font-semibold">Workspace access needs attention</h1>
          <p role="alert">{profileError}</p>
          <div className="flex gap-4">
            <button type="button" onClick={() => void refreshProfile()}>Try again</button>
            <button type="button" onClick={() => void signOut()}>Sign out</button>
          </div>
        </div>
      </main>
    );
  }

  return <>{children}</>;
}
