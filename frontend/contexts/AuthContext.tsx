"use client";

import { createContext, useCallback, useEffect, useState, type ReactNode } from "react";
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
  refreshProfile: () => Promise<void>;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadProfile(accessToken: string) {
    if (!accessToken) {
      setProfile(null);
      return;
    }
    try {
      setProfile(await getMe(accessToken));
    } catch {
      // getMe 401s when the local profile row doesn't exist yet (very first
      // sign-in, before /auth/provision runs) or the session just expired.
      // Either way there is no real role to gate on — the app keeps working
      // in demo mode rather than hard-failing here.
      setProfile(null);
    }
  }

  const refreshProfile = useCallback(async () => {
    const { data } = await supabase.auth.getSession();
    await loadProfile(data.session?.access_token ?? "");
  }, []);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setCurrentAccessToken(data.session?.access_token ?? "");
      setLoading(false);
      void loadProfile(data.session?.access_token ?? "");
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      setCurrentAccessToken(newSession?.access_token ?? "");
      // The provision flow refreshes right after writing app_metadata, so this
      // fires again with the refreshed token — which is what finally lets
      // /auth/me return the tenant_id/role just provisioned.
      void loadProfile(newSession?.access_token ?? "");
    });

    return () => subscription.subscription.unsubscribe();
  }, []);

  const value: AuthContextValue = {
    session,
    user: session?.user ?? null,
    profile,
    loading,
    refreshProfile,
    signOut: signOutService,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}