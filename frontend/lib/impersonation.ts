/** Client-side state for an Admin's read-only "view as" session.
 *
 * Kept in sessionStorage, so it belongs to one browser tab and dies with it.
 * While set, every backend call carries X-Impersonation-Session: the backend
 * then resolves the request as the viewed user and refuses anything but
 * reads. A write sent WITHOUT the header would run as the Admin instead, so
 * every API client attaches impersonationHeaders() — never only some calls.
 * The two deliberate exceptions write nothing governed: diagram rendering
 * (stateless SVG) and UI telemetry (the Admin's own browser activity). */

export type ActiveImpersonation = {
  sessionId: string;
  targetName: string;
  targetRole: string;
  expiresAt: string;
};

const STORAGE_KEY = "zoiko_impersonation";
export const IMPERSONATION_EVENT = "zoiko-impersonation-change";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function getImpersonation(): ActiveImpersonation | null {
  const raw = storage()?.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as ActiveImpersonation;
    if (!value.sessionId || new Date(value.expiresAt).getTime() <= Date.now()) {
      clearImpersonation();
      return null;
    }
    return value;
  } catch {
    clearImpersonation();
    return null;
  }
}

export function setImpersonation(value: ActiveImpersonation): void {
  storage()?.setItem(STORAGE_KEY, JSON.stringify(value));
  window.dispatchEvent(new Event(IMPERSONATION_EVENT));
}

export function clearImpersonation(): void {
  const store = storage();
  if (!store?.getItem(STORAGE_KEY)) return;
  store.removeItem(STORAGE_KEY);
  window.dispatchEvent(new Event(IMPERSONATION_EVENT));
}

export function impersonationHeaders(): Record<string, string> {
  const active = getImpersonation();
  return active ? { "X-Impersonation-Session": active.sessionId } : {};
}
