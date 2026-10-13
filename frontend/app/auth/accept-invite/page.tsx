"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, LockKeyhole, MailCheck } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { AuthError, provisionAndRefresh, updatePassword } from "@/services/auth.service";
import { BrandMark } from "@/components/layout/AppHeader";

/** Landing page for an Admin's invitation email (POST /users without a
 * password). Supabase's invite link signs the user in with tokens in the URL
 * fragment; here they choose their own password — no Admin ever knows it —
 * and the backend profile the Admin already created is linked to them. */
export default function AcceptInvitePage() {
  const router = useRouter();
  const [ready, setReady] = useState<"checking" | "ok" | "invalid">("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function establishSession() {
      // Invite links use the implicit flow: #access_token=…&refresh_token=…
      const fragment = new URLSearchParams(window.location.hash.slice(1));
      const accessToken = fragment.get("access_token");
      const refreshToken = fragment.get("refresh_token");
      if (accessToken && refreshToken) {
        await supabase.auth.setSession({ access_token: accessToken, refresh_token: refreshToken });
        // Keep the tokens out of history and any later copy-paste of the URL.
        window.history.replaceState(null, "", window.location.pathname);
      }
      const { data } = await supabase.auth.getSession();
      if (!cancelled) setReady(data.session ? "ok" : "invalid");
    }
    establishSession().catch(() => {
      if (!cancelled) setReady("invalid");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await updatePassword(password);
      const { data } = await supabase.auth.getSession();
      if (!data.session) throw new AuthError("Your invitation session expired. Ask your administrator to resend it.");
      await provisionAndRefresh(data.session.access_token, data.session.user.user_metadata ?? {});
      router.replace("/");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not finish setting up your account. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-bg px-5 py-10 text-ink">
      <div className="relative w-full max-w-md">
        <div className="relative overflow-hidden rounded-2xl border border-line bg-panel p-5 shadow-[0_18px_50px_rgba(11,95,122,0.10)] sm:p-6">
          <div className="mb-3 flex items-center gap-3">
            <BrandMark className="h-9 w-9" />
            <div>
              <p className="text-sm font-bold text-ink">ZoikoLogia</p>
              <p className="text-xs text-muted">Governance intelligence workspace</p>
            </div>
          </div>

          {ready === "checking" && <p className="text-sm text-muted">Checking your invitation…</p>}

          {ready === "invalid" && (
            <>
              <h2 className="text-2xl font-bold tracking-normal text-ink">Invitation link expired</h2>
              <p className="mt-1.5 text-sm leading-6 text-muted">
                This invitation link is invalid or has already been used. Ask your administrator to send a new one.
              </p>
              <p className="mt-3 text-center text-sm">
                <button type="button" onClick={() => router.push("/login")} className="font-semibold text-brand hover:underline">
                  Go to sign in
                </button>
              </p>
            </>
          )}

          {ready === "ok" && (
            <>
              <div className="mb-3">
                <h2 className="text-2xl font-bold tracking-normal text-ink">Welcome to ZoikoLogia</h2>
                <p className="mt-1.5 text-sm leading-6 text-muted">Choose a password to finish setting up your account.</p>
              </div>
              <form onSubmit={handleSubmit} className="space-y-2">
                {[
                  { id: "invite-password", label: "New password", value: password, set: setPassword },
                  { id: "invite-confirm", label: "Confirm password", value: confirm, set: setConfirm },
                ].map((field) => (
                  <div key={field.id}>
                    <label htmlFor={field.id} className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
                      {field.label}
                    </label>
                    <div className="relative">
                      <LockKeyhole size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                      <input
                        id={field.id}
                        type="password"
                        value={field.value}
                        onChange={(e) => field.set(e.target.value)}
                        autoComplete="new-password"
                        className="h-9 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
                      />
                    </div>
                  </div>
                ))}
                <p className="text-xs text-muted">At least 8 characters, with an uppercase letter, a lowercase letter and a number.</p>

                {error && (
                  <p role="alert" className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60"
                >
                  {submitting ? "Setting up..." : (
                    <>
                      Set password and continue
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </form>
            </>
          )}

          <div className="mt-5 flex items-center justify-center gap-1.5">
            <MailCheck size={14} className="text-muted" />
            <span className="text-xs text-muted">Only you will know this password.</span>
          </div>
        </div>
      </div>
    </main>
  );
}
