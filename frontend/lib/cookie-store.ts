/**
 * Client cookies as a React external store, for useSyncExternalStore.
 *
 * Reading a cookie in a useEffect and copying it into state renders the page
 * twice (default, then cookie value) and trips react-hooks/set-state-in-effect.
 * useSyncExternalStore instead renders the server snapshot during SSR and
 * hydration, then the real cookie value — with no effect. document.cookie has
 * no change event, so writes must go through writeCookie() to notify readers.
 */
const listeners = new Set<() => void>();

export function subscribeCookies(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function writeCookie(name: string, value: string, maxAgeSeconds: number): void {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAgeSeconds}`;
  listeners.forEach((listener) => listener());
}
