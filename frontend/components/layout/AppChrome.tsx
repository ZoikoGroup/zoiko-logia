"use client";

import { usePathname } from "next/navigation";
import { ReactNode, useState } from "react";
import { Sidebar } from "./Sidebar";
import { AppHeader } from "./AppHeader";
import { ImpersonationBanner } from "@/components/shell/ImpersonationBanner";

export function AppChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

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
        {children}
      </div>
      <ImpersonationBanner />
    </>
  );
}
