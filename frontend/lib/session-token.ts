/**
 * Module-level cache of the current Supabase access token, kept in sync by
 * AuthContext on every getSession()/onAuthStateChange event. Every page
 * component already calls lib/api.ts's synchronous getAuthToken() — routing
 * it through this instead of an async supabase.auth.getSession() call avoids
 * making that async and rippling through every call site.
 */
let currentAccessToken = "";

export function getCurrentAccessToken(): string {
  return currentAccessToken;
}

export function setCurrentAccessToken(token: string): void {
  currentAccessToken = token;
}
