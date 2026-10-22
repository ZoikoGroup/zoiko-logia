import { supabase } from "@/lib/supabase";
import { getCurrentAccessToken, setCurrentAccessToken } from "@/lib/session-token";

let pendingRefresh: Promise<string> | null = null;

/** A request is already handling the auth event emitted by its own refresh. */
export function isSessionRefreshInProgress(): boolean {
  return pendingRefresh !== null;
}

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

/** Seconds until the JWT expires (negative once expired); null if unreadable. */
function secondsLeft(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload.exp === "number" ? payload.exp - Date.now() / 1000 : null;
  } catch {
    return null;
  }
}

/** Retry authentication once; concurrent 401s share one session refresh. */
export async function fetchWithSession(url: string, token: string, init?: RequestInit): Promise<Response> {
  if (!token) {
    const { data } = await supabase.auth.getSession();
    token = data.session?.access_token ?? "";
  }
  if (!token) throw new Error("Sign in to load these records.");
  // Renew a token that has expired (or is about to) before sending it. After
  // the tab sat idle or the laptop slept, background requests (the bell)
  // went out with the old token, failed with 401 and could sign the user out.
  const left = secondsLeft(token);
  if (left !== null && left < 60) {
    const current = getCurrentAccessToken();
    const fresher = current && current !== token && (secondsLeft(current) ?? 0) >= 60 ? current : await refreshToken();
    if (fresher) token = fresher;
  }
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
