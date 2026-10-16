"use client";

import { usePathname } from "next/navigation";
import { ReactNode, useState } from "react";
import { Sidebar } from "./Sidebar";
import { AppHeader } from "./AppHeader";
import { ImpersonationBanner } from "@/components/shell/ImpersonationBanner";
import { useRole } from "@/components/shell/RoleProvider";
import { Loader2 } from "lucide-react";

export function AppChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { roleReady } = useRole();

  if (pathname.startsWith("/auth/") || pathname === "/login" || pathname === "/signup") {
    return <>{children}</>;
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
        {roleReady ? children : (
          <main className="flex flex-1 items-center justify-center p-8 text-muted" aria-busy="true">
            <Loader2 size={20} className="animate-spin" aria-label="Loading your workspace" />
          </main>
        )}
      </div>
      <ImpersonationBanner />
    </>
  );
}
