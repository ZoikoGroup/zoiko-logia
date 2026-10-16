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
  const { session, profile, loading: authLoading, profileLoading } = useAuth();
  // Wait for the profile before the first fetch: the cache key includes the
  // role, so fetching earlier loaded every page twice (once with no role,
  // again when the profile arrived).
  const waiting = authLoading || Boolean(session && profileLoading && !profile);
  const userId = session?.user?.id ?? "";
  const cacheKey = `${userId}:${profile?.tenant_id ?? ""}:${profile?.role ?? ""}:${key}`;
  const [version, setVersion] = useState(0);
  // One id per request: a new page key or a reload() starts a new request.
  // Loading, error and data are worked out from it during render, so the
  // effect never has to reset state before it fetches.
  const requestId = `${cacheKey}#${version}`;
  const [snapshot, setSnapshot] = useState<{ key: string; data: T | null }>({ key: cacheKey, data: null });
  const [failure, setFailure] = useState<{ request: string; message: string }>({ request: "", message: "" });
  const [settled, setSettled] = useState("");
  const fresh = useRef(false);
  const inFlight = useRef(false);
  const reload = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    fresh.current = true;
    setVersion((v) => v + 1);
  }, []);
  const token = session ? getAuthToken() : "";

  // The last result for this page shows at once while the live request runs.
  const data = !session ? null
    : snapshot.key === cacheKey ? snapshot.data
    : ((memory.get(cacheKey) as T | undefined) ?? null);
  const error = session && failure.request === requestId ? failure.message : "";
  const loading = waiting || (Boolean(token) && settled !== requestId);

  useEffect(() => {
    if (waiting || !token) {
      if (!authLoading && !token) memory.clear();
      return;
    }
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
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          memory.delete(cacheKey);
          setSnapshot({ key: cacheKey, data: null });
        }
        setFailure({ request: requestId, message: err instanceof Error ? err.message : "Could not load live data." });
      })
      .finally(() => {
        clearTimeout(timer);
        if (!controller.signal.aborted) {
          inFlight.current = false;
          setSettled(requestId);
          controller.abort();
        }
      });
    return () => { clearTimeout(timer); controller.abort(); inFlight.current = false; };
    // fetcher reads its options from refs at every call site; key changes go
    // through reload().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting, token, userId, cacheKey, requestId, timeoutMs]);

  return { data, error, loading, signedOut: !authLoading && !session, reload };
}
