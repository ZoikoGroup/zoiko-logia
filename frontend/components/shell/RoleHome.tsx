"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { homePathFor } from "@/lib/roles";

/** Wraps the "/" home page so each role lands on its own home: every route
 * that ends at "/" (MFA step, proxy redirects, bookmarks) then sends a Learner
 * to the learning workspace instead of the governance Command Center. */
export function RoleHome({ children }: { children: ReactNode }) {
  const { profile } = useAuth();
  const router = useRouter();
  const home = homePathFor(profile?.role);

  useEffect(() => {
    if (home !== "/") router.replace(home);
  }, [home, router]);

  return home === "/" ? <>{children}</> : null;
}
