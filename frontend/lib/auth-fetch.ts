import { supabase } from "@/lib/supabase";
import { getCurrentAccessToken, setCurrentAccessToken } from "@/lib/session-token";

let pendingRefresh: Promise<string> | null = null;

async function refreshToken(): Promise<string> {
  if (!pendingRefresh) {
    pendingRefresh = supabase.auth.refreshSession().then(({ data, error }) => {
      const token = error ? "" : data.session?.access_token ?? "";
      if (token) setCurrentAccessToken(token);
      return token;
    }).catch(() => "").finally(() => { pendingRefresh = null; });
  }
  return pendingRefresh;
}

/** Retry authentication once; concurrent 401s share one session refresh. */
export async function fetchWithSession(url: string, token: string, init?: RequestInit): Promise<Response> {
  if (!token) {
    const { data } = await supabase.auth.getSession();
    token = data.session?.access_token ?? "";
  }
  if (!token) throw new Error("Sign in to load these records.");
  const send = (accessToken: string) => {
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);
    return fetch(url, { ...init, headers });
  };
  const response = await send(token);
  if (response.status !== 401 || init?.signal?.aborted) return response;
  // Another request may already have refreshed the token while this one ran.
  const current = getCurrentAccessToken();
  const next = current && current !== token ? current : await refreshToken();
  if (!next || init?.signal?.aborted) return response;
  return send(next);
}
