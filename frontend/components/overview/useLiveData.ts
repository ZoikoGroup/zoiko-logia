"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { ApiError, getAuthToken } from "@/lib/api";

type Fetcher<T> = (token: string, signal: AbortSignal, fresh: boolean) => Promise<T>;

// Last result per page and user, kept in memory for this tab only (never in
// storage, never on the server). Moving between Overview pages shows the
// last numbers at once while the live request runs in the background.
const memory = new Map<string, unknown>();
/** Loads an Overview view model once the session is known, and again on
 * `reload()` (which bypasses the server's short cache). Shows the last result
 * for this page immediately when there is one. */
export function useLiveData<T>(key: string, fetcher: Fetcher<T>, timeoutMs = 45_000) {
  const { session, profile, loading: authLoading } = useAuth();
  const userId = session?.user?.id ?? "";
  const cacheKey = `${userId}:${profile?.tenant_id ?? ""}:${profile?.role ?? ""}:${key}`;
  const [snapshot, setSnapshot] = useState<{ key: string; data: T | null }>({ key: cacheKey, data: null });
  const data = session && snapshot.key === cacheKey ? snapshot.data : null;
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const fresh = useRef(false);
  const inFlight = useRef(false);
  const reload = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    fresh.current = true;
    setLoading(true);
    setVersion((v) => v + 1);
  }, []);
  const token = session ? getAuthToken() : "";

  useEffect(() => {
    if (authLoading || !token) {
      if (!authLoading) {
        memory.clear();
        setSnapshot({ key: cacheKey, data: null });
        setError("");
        setLoading(false);
      }
      return;
    }
    setSnapshot({ key: cacheKey, data: (memory.get(cacheKey) as T | undefined) ?? null });
    setError("");
    setLoading(true);
    const controller = new AbortController();
    const wantFresh = fresh.current;
    fresh.current = false;
    inFlight.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("The server is taking too long. Please retry.")), timeoutMs);
    });
    Promise.race([fetcher(token, controller.signal, wantFresh), deadline])
      .then((result) => {
        if (controller.signal.aborted) return;
        memory.set(cacheKey, result);
        setSnapshot({ key: cacheKey, data: result });
        setError("");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          memory.delete(cacheKey);
          setSnapshot({ key: cacheKey, data: null });
        }
        setError(err instanceof Error ? err.message : "Could not load live data.");
      })
      .finally(() => {
        clearTimeout(timer);
        if (!controller.signal.aborted) {
          inFlight.current = false;
          setLoading(false);
          controller.abort();
        }
      });
    return () => { clearTimeout(timer); controller.abort(); inFlight.current = false; };
    // fetcher reads its options from refs at every call site; key changes go
    // through reload().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, token, userId, cacheKey, version, timeoutMs]);

  return { data, error: snapshot.key === cacheKey && session ? error : "", loading: authLoading || (Boolean(token) && loading), signedOut: !authLoading && !session, reload };
}
