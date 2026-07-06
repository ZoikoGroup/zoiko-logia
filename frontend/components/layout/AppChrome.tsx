"use client";

import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { AppHeader } from "./AppHeader";

export function AppChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <>
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <AppHeader />
        {children}
      </div>
    </>
  );
}
