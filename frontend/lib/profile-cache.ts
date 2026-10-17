import type { UserPublic } from "@/lib/api";

// Cache of the last /auth/me result, shared by this browser's tabs so a new
// tab knows the role at once instead of rendering the fail-closed Learner view
// until /auth/me answers. Only a UX shortcut: the backend still enforces every
// permission, and the entry is keyed to the Supabase user id, re-verified on
// load and dropped on sign-out or any failed re-verification.
const PROFILE_CACHE_KEY = "zoiko_profile";

export function readCachedProfile(userId: string): UserPublic | null {
  try {
    const raw = localStorage.getItem(PROFILE_CACHE_KEY);
    const cached = raw ? (JSON.parse(raw) as UserPublic) : null;
    return cached?.id === userId ? cached : null;
  } catch {
    return null;
  }
}

export function writeCachedProfile(profile: UserPublic): void {
  try {
    localStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify(profile));
  } catch {
    // Storage unavailable (private mode, quota) — the nav just waits for /auth/me.
  }
}

export function clearCachedProfile(): void {
  try {
    localStorage.removeItem(PROFILE_CACHE_KEY);
  } catch {
    // Nothing cached to clear.
  }
}

// Sign-in already has the verified profile in hand (POST /auth/provision
// returns it). Handing it over here lets the app render at once instead of
// waiting for another /auth/me round trip — that wait was most of the
// "Signing in…" delay. AuthProvider (contexts/AuthContext.tsx) picks it up.
export const PROFILE_PRIMED_EVENT = "zoiko:profile-primed";

export function primeProfile(profile: UserPublic): void {
  writeCachedProfile(profile);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<UserPublic>(PROFILE_PRIMED_EVENT, { detail: profile }));
  }
}
