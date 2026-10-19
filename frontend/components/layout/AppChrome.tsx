"use client";

import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { AppHeader } from "./AppHeader";
import { ImpersonationBanner } from "@/components/shell/ImpersonationBanner";
import { useRole } from "@/components/shell/RoleProvider";
import { Loader2 } from "lucide-react";
import { SuperAdminChrome } from "@/components/platform/SuperAdminChrome";
import { useAuth } from "@/hooks/useAuth";
import { canAccessPath } from "@/lib/nav";
import { homePathFor } from "@/lib/roles";

export function AppChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { roleReady, realRole } = useRole();
  const { session } = useAuth();
  const router = useRouter();
  // A signed-in user may only open the pages their own (verified) role can
  // reach — a Learner typing an Admin URL goes back to their learning home.
  // Uses the real role, not an Admin's "Viewing as" preview. The backend
  // still enforces every permission on its own.
  const blocked = Boolean(session) && roleReady && !canAccessPath(pathname, realRole);
  useEffect(() => {
    if (blocked) router.replace(homePathFor(realRole));
  }, [blocked, realRole, router]);

  if (pathname.startsWith("/auth/") || pathname === "/login" || pathname === "/signup") {
    return <>{children}</>;
  }

  // Platform control plane: its own shell, never the tenant sidebar.
  if (pathname === "/super-admin" || pathname.startsWith("/super-admin/")) {
    return <SuperAdminChrome>{children}</SuperAdminChrome>;
  }

  if (pathname === "/ask-kriton") {
    return (
      <>
        {children}
        <ImpersonationBanner />
      </>
    );
  }

  return (
    <>
      <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
      <div className="flex-1 min-w-0 flex flex-col">
        <AppHeader onMenuClick={() => setMobileNavOpen(true)} />
        {/* Until the signed-in user's real role is known, pages would render
            for the fail-closed Learner role and then switch — show a neutral
            loading state instead. */}
        {roleReady && !blocked ? children : (
          <main className="flex flex-1 items-center justify-center p-8 text-muted" aria-busy="true">
            <Loader2 size={20} className="animate-spin" aria-label="Loading your workspace" />
          </main>
        )}
      </div>
      <ImpersonationBanner />
    </>
  );
}
