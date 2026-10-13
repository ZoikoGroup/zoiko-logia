"use client";

import { createContext, useContext, useSyncExternalStore, ReactNode } from "react";
import { RoleCode, DEFAULT_ROLE, ROLE_COOKIE, canPreviewRoles, resolveDisplayRole, resolveEffectiveRole } from "@/lib/roles";
import { useAuth } from "@/hooks/useAuth";
import { readCookie, subscribeCookies, writeCookie } from "@/lib/cookie-store";

type RoleContextValue = {
  /** The role the UI renders as: the real role, or an Admin's preview choice. */
  role: RoleCode;
  /** The signed-in user's verified role (or the demo role with no session). */
  realRole: RoleCode;
  /** Whether the "Viewing as" switcher may change the displayed role. */
  canPreview: boolean;
  /** False while a signed-in user's real role is still being fetched —
   * role-gated UI should wait rather than render the fail-closed fallback. */
  roleReady: boolean;
  setRole: (role: RoleCode) => void;
};

const RoleContext = createContext<RoleContextValue | null>(null);

function readRoleCookie(): RoleCode {
  return (readCookie(ROLE_COOKIE) ?? DEFAULT_ROLE) as RoleCode;
}

function serverRole(): RoleCode {
  return DEFAULT_ROLE;
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const { profile, session, loading, profileLoading } = useAuth();
  // The demo-mode cookie role: DEFAULT_ROLE during SSR/hydration, then the
  // cookie's value — read as an external store rather than copied into state
  // from an effect.
  const demoRole = useSyncExternalStore(subscribeCookies, readRoleCookie, serverRole);

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
  const realRole = resolveEffectiveRole(profile?.role, demoRole, Boolean(session));
  // A signed-in Admin previews the switcher's choice; nobody else can change
  // their role this way (see resolveDisplayRole). The backend still enforces
  // the real role on every request.
  const role = resolveDisplayRole(realRole, demoRole, Boolean(session));
  const canPreview = canPreviewRoles(realRole, Boolean(session));
  // Only the first fetch blocks: a background re-fetch (e.g. on the hourly
  // TOKEN_REFRESHED) keeps showing the profile already loaded.
  const roleReady = !loading && !(session && profileLoading && !profile);

  function setRole(next: RoleCode) {
    writeCookie(ROLE_COOKIE, next, 60 * 60 * 24 * 7);
  }

  return (
    <RoleContext.Provider value={{ role, realRole, canPreview, roleReady, setRole }}>{children}</RoleContext.Provider>
  );
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error("useRole must be used within a RoleProvider");
  return ctx;
}
