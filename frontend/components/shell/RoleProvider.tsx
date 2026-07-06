"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { RoleCode, DEFAULT_ROLE, ROLE_COOKIE } from "@/lib/roles";

type RoleContextValue = {
  role: RoleCode;
  setRole: (role: RoleCode) => void;
};

const RoleContext = createContext<RoleContextValue | null>(null);

function readRoleCookie(): RoleCode {
  if (typeof document === "undefined") return DEFAULT_ROLE;
  const match = document.cookie.match(new RegExp(`(?:^|; )${ROLE_COOKIE}=([^;]*)`));
  return (match ? decodeURIComponent(match[1]) : DEFAULT_ROLE) as RoleCode;
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<RoleCode>(DEFAULT_ROLE);

  useEffect(() => {
    setRoleState(readRoleCookie());
  }, []);

  function setRole(next: RoleCode) {
    document.cookie = `${ROLE_COOKIE}=${encodeURIComponent(next)}; path=/; max-age=${60 * 60 * 24 * 7}`;
    setRoleState(next);
  }

  return <RoleContext.Provider value={{ role, setRole }}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error("useRole must be used within a RoleProvider");
  return ctx;
}
