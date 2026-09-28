"use client";

import { createContext, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import { setCurrentAccessToken } from "@/lib/session-token";
import { signOut as signOutService } from "@/services/auth.service";
import { getMe, type UserPublic } from "@/lib/api";

export type AuthContextValue = {
  session: Session | null;
  user: User | null;
  /** The provisioned backend profile (POST /auth/provision + GET /auth/me).
   * Empty until the app has both a Supabase session and a local profile row,
   * so UI that gates on the real role treats null as "no real role yet". */
  profile: UserPublic | null;
  loading: boolean;
  /** True while a GET /auth/me for the current session is in flight — so UI
   * never gates on a role that simply hasn't arrived yet. */
  profileLoading: boolean;
  refreshProfile: () => Promise<void>;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

// Per-tab cache of the last /auth/me result. Only a UX shortcut for the nav:
// the backend still enforces every permission, and the entry is keyed to the
// Supabase user id and dropped on sign-out or any failed re-verification.
const PROFILE_CACHE_KEY = "zoiko_profile";

function readCachedProfile(userId: string): UserPublic | null {
  try {
    const raw = sessionStorage.getItem(PROFILE_CACHE_KEY);
    const cached = raw ? (JSON.parse(raw) as UserPublic) : null;
    return cached?.id === userId ? cached : null;
  } catch {
    return null;
  }
}

function writeCachedProfile(profile: UserPublic): void {
  try {
    sessionStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify(profile));
  } catch {
    // Storage unavailable (private mode, quota) — the nav just waits for /auth/me.
  }
}

function clearCachedProfile(): void {
  try {
    sessionStorage.removeItem(PROFILE_CACHE_KEY);
  } catch {
    // Nothing cached to clear.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<UserPublic | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [profileLoading, setProfileLoading] = useState(false);
  // Sign-in fires several auth events back to back (SIGNED_IN, then
  // TOKEN_REFRESHED once /auth/provision has run), each starting its own
  // getMe. Only the latest request may write the profile — otherwise a slow
  // early 401 (sent before provisioning finished) can land last and wipe the
  // real role, leaving the user stuck on the fail-closed Learner role.
  const latestProfileRequest = useRef(0);

  async function loadProfile(currentSession: Session | null) {
    const requestId = ++latestProfileRequest.current;
    const accessToken = currentSession?.access_token ?? "";
    if (!currentSession || !accessToken) {
      clearCachedProfile();
      setProfile(null);
      setProfileLoading(false);
      return;
    }
    // Show the last verified profile for this same user straight away so a
    // page reload doesn't hold the role-gated nav on a round trip to
    // /auth/me; the fetch below still re-verifies it in the background.
    const cached = readCachedProfile(currentSession.user.id);
    if (cached) setProfile((prev) => (prev?.id === cached.id ? prev : cached));
    setProfileLoading(true);
    let next: UserPublic | null;
    try {
      next = await getMe(accessToken);
    } catch {
      // getMe 401s when the local profile row doesn't exist yet (very first
      // sign-in, before /auth/provision runs) or the session just expired.
      // Either way there is no real role to gate on — the app keeps working
      // in demo mode rather than hard-failing here.
      next = null;
    }
    if (requestId !== latestProfileRequest.current) return;
    if (next) writeCachedProfile(next);
    else clearCachedProfile();
    setProfile(next);
    setProfileLoading(false);
  }

  const refreshProfile = useCallback(async () => {
    const { data } = await supabase.auth.getSession();
    await loadProfile(data.session);
  }, []);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setCurrentAccessToken(data.session?.access_token ?? "");
      void loadProfile(data.session);
      setSessionLoading(false);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      setCurrentAccessToken(newSession?.access_token ?? "");
      // The provision flow refreshes right after writing app_metadata, so this
      // fires again with the refreshed token — which is what finally lets
      // /auth/me return the tenant_id/role just provisioned.
      void loadProfile(newSession);
    });

    return () => subscription.subscription.unsubscribe();
  }, []);

  const value: AuthContextValue = {
    session,
    user: session?.user ?? null,
    profile,
    loading: sessionLoading,
    profileLoading,
    refreshProfile,
    signOut: signOutService,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}