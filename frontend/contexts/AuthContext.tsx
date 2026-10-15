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

// Cache of the last /auth/me result, shared by this browser's tabs so a new
// tab knows the role at once instead of rendering the fail-closed Learner view
// until /auth/me answers. Only a UX shortcut: the backend still enforces every
// permission, and the entry is keyed to the Supabase user id, re-verified on
// load and dropped on sign-out or any failed re-verification.
const PROFILE_CACHE_KEY = "zoiko_profile";

function readCachedProfile(userId: string): UserPublic | null {
  try {
    const raw = localStorage.getItem(PROFILE_CACHE_KEY);
    const cached = raw ? (JSON.parse(raw) as UserPublic) : null;
    return cached?.id === userId ? cached : null;
  } catch {
    return null;
  }
}

function writeCachedProfile(profile: UserPublic): void {
  try {
    localStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify(profile));
  } catch {
    // Storage unavailable (private mode, quota) — the nav just waits for /auth/me.
  }
}

function clearCachedProfile(): void {
  try {
    localStorage.removeItem(PROFILE_CACHE_KEY);
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
  // The verified profile, readable from the auth listener without re-subscribing.
  const profileRef = useRef<UserPublic | null>(null);

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
    profileRef.current = next;
    // Keep the same object when nothing changed, so pages keyed on the
    // profile don't reload.
    setProfile((prev) => (prev && next && JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
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

    const { data: subscription } = supabase.auth.onAuthStateChange((event, newSession) => {
      // getSession() above already handled the initial session.
      if (event === "INITIAL_SESSION") return;
      setCurrentAccessToken(newSession?.access_token ?? "");
      // Supabase re-emits SIGNED_IN / TOKEN_REFRESHED on tab focus and every
      // token refresh. Keep the same session object when the user and token
      // are unchanged, so nothing downstream re-renders or refetches.
      setSession((prev) =>
        prev && newSession && prev.access_token === newSession.access_token && prev.user.id === newSession.user.id
          ? prev
          : newSession);
      // The provision flow refreshes right after writing app_metadata, so this
      // fires again with the refreshed token — which is what finally lets
      // /auth/me return the tenant_id/role just provisioned. Once a profile is
      // loaded for this user, a plain refresh doesn't need another /auth/me.
      const loaded = profileRef.current;
      if (newSession && loaded && loaded.id === newSession.user.id && event !== "USER_UPDATED") return;
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