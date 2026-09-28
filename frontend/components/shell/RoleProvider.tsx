"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { RoleCode, DEFAULT_ROLE, ROLE_COOKIE, resolveEffectiveRole } from "@/lib/roles";
import { useAuth } from "@/hooks/useAuth";

type RoleContextValue = {
  role: RoleCode;
  /** False while a signed-in user's real role is still being fetched —
   * role-gated UI should wait rather than render the fail-closed fallback. */
  roleReady: boolean;
  setRole: (role: RoleCode) => void;
};

const RoleContext = createContext<RoleContextValue | null>(null);

function readRoleCookie(): RoleCode {
  if (typeof document === "undefined") return DEFAULT_ROLE;
  const match = document.cookie.match(new RegExp(`(?:^|; )${ROLE_COOKIE}=([^;]*)`));
  return (match ? decodeURIComponent(match[1]) : DEFAULT_ROLE) as RoleCode;
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const { profile, session, loading, profileLoading } = useAuth();
  const [demoRole, setDemoRole] = useState<RoleCode>(DEFAULT_ROLE);

  useEffect(() => {
    setDemoRole(readRoleCookie());
  }, []);

  // The provisioned profile's role (AuthContext → getMe) is what the app
  // gates on. The zoiko_role cookie stays exactly as it was — a demo-mode
  // switcher for previews without a real profile — but it never overrides a
  // real role: a "Source Admin" profile keeps gating as Source Admin no
  // matter what the cookie says.
  //
  // Fail closed once a real session exists: if the user is signed in but
  // /auth/me failed or hasn't produced a known role, the effective role
  // degrades to UNVERIFIED_ROLE rather than falling back to the cookie
  // demo default (Admin). Only the genuinely session-less preview keeps the
  // cookie role. While the profile is still loading the role is not yet
  // known: stay fail-closed (never the Admin demo default) and report
  // roleReady=false so the nav waits instead of flashing the Learner menu.
  const role = resolveEffectiveRole(profile?.role, demoRole, Boolean(session));
  // Only the first fetch blocks: a background re-fetch (e.g. on the hourly
  // TOKEN_REFRESHED) keeps showing the profile already loaded.
  const roleReady = !loading && !(session && profileLoading && !profile);

  function setRole(next: RoleCode) {
    document.cookie = `${ROLE_COOKIE}=${encodeURIComponent(next)}; path=/; max-age=${60 * 60 * 24 * 7}`;
    setDemoRole(next);
  }

  return <RoleContext.Provider value={{ role, roleReady, setRole }}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error("useRole must be used within a RoleProvider");
  return ctx;
}
