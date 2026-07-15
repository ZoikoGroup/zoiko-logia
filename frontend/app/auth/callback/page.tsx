"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { provisionAndRefresh } from "@/services/auth.service";

/** Google OAuth lands here after Supabase's redirect. The browser client
 * auto-exchanges the URL's auth code for a session on load
 * (detectSessionInUrl, on by default) — this page just waits for that,
 * provisions the local profile on first-ever login (no email-verification
 * gate for OAuth, unlike the password flow), then sends the user on to
 * the dashboard. */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function finish() {
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        // Give the client SDK a moment to process the redirect URL, then
        // fall back to the auth state change event if still not ready.
        const { data: subscription } = supabase.auth.onAuthStateChange((event, newSession) => {
          if (newSession && !cancelled) {
            subscription.subscription.unsubscribe();
            complete(newSession.access_token, newSession.user.user_metadata ?? {});
          }
        });
        return;
      }

      await complete(session.access_token, session.user.user_metadata ?? {});
    }

    async function complete(accessToken: string, metadata: Record<string, unknown>) {
      try {
        await provisionAndRefresh(accessToken, metadata);
        if (!cancelled) router.replace("/");
      } catch {
        if (!cancelled) setError("Could not complete sign-in. Please try again.");
      }
    }

    finish();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-bg text-ink">
      <p className="text-sm text-muted">{error || "Finishing sign-in…"}</p>
    </main>
  );
}
