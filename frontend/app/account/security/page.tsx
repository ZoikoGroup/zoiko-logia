"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { ApiError, getAuthToken, getMfaStatus, signOutAllSessions, type MfaStatus } from "@/lib/api";
import {
  AuthError,
  confirmTotpEnrollment,
  listTotpFactors,
  removeTotpFactor,
  signOut,
  startTotpEnrollment,
  type TotpEnrollment,
  type TotpFactor,
} from "@/services/auth.service";

type SecurityState = [TotpFactor[], MfaStatus | null];

function loadSecurityState(): Promise<SecurityState> {
  // The policy endpoint is informational; the page still works without it.
  return Promise.all([listTotpFactors(), getMfaStatus(getAuthToken()).catch(() => null)]);
}

/** Self-service account security: TOTP two-step verification and session
 * revocation. Enrolment runs through Supabase Auth; the backend only reads
 * the resulting assurance level from the token. */
export default function AccountSecurityPage() {
  const router = useRouter();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [factors, setFactors] = useState<TotpFactor[]>([]);
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const applySecurityState = useCallback(([nextFactors, nextStatus]: SecurityState) => {
    setFactors(nextFactors.filter((f) => f.status === "verified"));
    setStatus(nextStatus);
  }, []);

  const refresh = async () => applySecurityState(await loadSecurityState());

  useEffect(() => {
    let cancelled = false;
    loadSecurityState()
      .then((state) => {
        if (!cancelled) applySecurityState(state);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof AuthError ? err.message : "Could not load your security settings.");
      });
    return () => {
      cancelled = true;
    };
  }, [applySecurityState]);

  async function run(action: () => Promise<void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof AuthError || err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const beginEnrollment = () =>
    run(async () => {
      setCode("");
      setEnrollment(await startTotpEnrollment());
    });

  const finishEnrollment = (e: FormEvent) => {
    e.preventDefault();
    if (!enrollment) return;
    return run(async () => {
      await confirmTotpEnrollment(enrollment.factorId, code);
      setEnrollment(null);
      setNotice("Two-step verification is on. You'll be asked for a code each time you sign in.");
      await refresh();
    });
  };

  const removeFactor = (factor: TotpFactor) =>
    run(async () => {
      await removeTotpFactor(factor.id);
      setNotice("Authenticator app removed.");
      await refresh();
    });

  const revokeAllSessions = () =>
    run(async () => {
      await signOutAllSessions(getAuthToken());
      await signOut();
      router.replace("/login");
    });

  const mfaOn = factors.length > 0;
  const mustEnroll = Boolean(status?.required_for_privileged && status.privileged_role && !mfaOn);

  return (
    <PageShell
      title="Account security"
      subtitle="Two-step verification and active sessions for your account."
    >
      {mustEnroll && (
        <p role="alert" className="mb-4 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-sm text-ink">
          Your role can change governed records, and this workspace requires two-step verification for those
          actions. Set up an authenticator app below, then sign in again.
        </p>
      )}
      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-sm text-bad">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-4 rounded-lg border border-ok/25 bg-ok/10 px-3 py-2 text-sm text-ink">
          {notice}
        </p>
      )}

      <Card title="Two-step verification" className="mb-4">
        <div className="mb-3 flex items-center gap-2">
          <Pill tone={mfaOn ? "ok" : "neutral"}>{mfaOn ? "On" : "Off"}</Pill>
          {status && (
            <span className="text-xs text-muted">
              This session: {status.current_aal === "aal2" ? "verified with a code" : "password or single sign-on only"}
            </span>
          )}
        </div>

        {factors.length > 0 && (
          <ul className="mb-3 divide-y divide-line rounded-lg border border-line">
            {factors.map((factor) => (
              <li key={factor.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="text-ink">{factor.friendlyName}</span>
                <button
                  type="button"
                  onClick={() => removeFactor(factor)}
                  disabled={busy}
                  className="text-xs text-bad hover:underline disabled:opacity-60"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        {enrollment ? (
          <form onSubmit={finishEnrollment} className="space-y-3">
            <p className="text-sm text-muted">
              Scan this QR code with an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password,
              etc.), then enter the 6-digit code it shows.
            </p>
            {/* Supabase returns the QR code as an SVG data URL. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={enrollment.qrCode} alt="QR code for your authenticator app" className="h-44 w-44 rounded-lg bg-white p-2" />
            <p className="text-xs text-muted">
              Can&apos;t scan? Enter this key manually:{" "}
              <code className="break-all rounded bg-soft px-1.5 py-0.5 text-ink">{enrollment.secret}</code>
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <label htmlFor="totp-code" className="mb-1.5 block text-xs font-medium text-muted">
                  Verification code
                </label>
                <input
                  id="totp-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  className="w-36 rounded-lg border border-line bg-soft px-3 py-2 text-sm tracking-[0.3em] text-ink outline-none focus:border-brand"
                />
              </div>
              <button
                type="submit"
                disabled={busy || code.length !== 6}
                className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-2 disabled:opacity-60"
              >
                {busy ? "Verifying..." : "Verify and turn on"}
              </button>
              <button
                type="button"
                onClick={() => setEnrollment(null)}
                disabled={busy}
                className="rounded-lg border border-line px-4 py-2 text-sm text-ink hover:bg-soft disabled:opacity-60"
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          !mfaOn && (
            <button
              type="button"
              onClick={beginEnrollment}
              disabled={busy}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-2 disabled:opacity-60"
            >
              Set up authenticator app
            </button>
          )
        )}
      </Card>

      <Card title="Sessions">
        <p className="mb-3 text-sm text-muted">
          Signs you out everywhere, including devices you no longer have. You&apos;ll need to sign in again here too.
        </p>
        <button
          type="button"
          onClick={revokeAllSessions}
          disabled={busy}
          className="rounded-lg border border-bad/40 px-4 py-2 text-sm font-semibold text-bad hover:bg-bad/10 disabled:opacity-60"
        >
          Sign out of all sessions
        </button>
      </Card>
    </PageShell>
  );
}
