"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Copy, KeyRound } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { BACKEND_ROLES } from "@/lib/roles";
import {
  ApiError,
  createServiceAccount,
  getAuthToken,
  issueServiceAccountKey,
  listServiceAccounts,
  listUsers,
  revokeServiceAccountKey,
  type ServiceAccount,
  type ServiceAccountKey,
  type UserListItem,
} from "@/lib/api";

// Administration needs a person; an API key never holds Admin.
const SERVICE_ROLES = BACKEND_ROLES.filter((r) => r !== "Admin");
const KEY_LIFETIMES = [30, 90, 180, 365];

function keyStatus(key: ServiceAccountKey): { label: string; tone: "ok" | "neutral" | "bad" } {
  if (key.revoked_at) return { label: "Revoked", tone: "neutral" };
  if (new Date(key.expires_at).getTime() <= Date.now()) return { label: "Expired", tone: "bad" };
  return { label: "Active", tone: "ok" };
}

function day(value: string | null): string {
  return value ? new Date(value).toLocaleDateString([], { dateStyle: "medium" }) : "—";
}

/** Non-interactive identities for integrations. Each has a named owner and a
 * non-Admin role; its API keys expire, can be rotated, and are shown once. */
export default function ServiceAccountsPage() {
  const [accounts, setAccounts] = useState<ServiceAccount[]>([]);
  const [people, setPeople] = useState<UserListItem[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [role, setRole] = useState<string>(SERVICE_ROLES[0]);
  const [owner, setOwner] = useState("");
  const [lifetime, setLifetime] = useState<Record<string, number>>({});
  const [issued, setIssued] = useState<{ accountName: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setAccounts(await listServiceAccounts(getAuthToken()));
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listServiceAccounts(getAuthToken()), listUsers(getAuthToken())])
      .then(([nextAccounts, users]) => {
        if (cancelled) return;
        setAccounts(nextAccounts);
        const active = users.filter((u) => u.is_active);
        setPeople(active);
        setOwner((current) => current || active[0]?.id || "");
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError && err.status === 403 ? "Admin role required." : "Could not load service accounts.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function run(action: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    return run(async () => {
      await createServiceAccount(getAuthToken(), { name, description, role, owner_user_id: owner });
      setName("");
      setDescription("");
    });
  }

  function handleIssue(account: ServiceAccount) {
    return run(async () => {
      const result = await issueServiceAccountKey(getAuthToken(), account.id, lifetime[account.id] ?? 90);
      setCopied(false);
      setIssued({ accountName: account.name, key: result.key });
    });
  }

  function handleRevoke(account: ServiceAccount, key: ServiceAccountKey) {
    if (!window.confirm(`Revoke key ${key.key_prefix}… for ${account.name}? Integrations using it stop working immediately.`)) return;
    return run(() => revokeServiceAccountKey(getAuthToken(), account.id, key.id));
  }

  async function copyKey() {
    if (!issued) return;
    await navigator.clipboard.writeText(issued.key);
    setCopied(true);
  }

  return (
    <PageShell
      title="Service accounts"
      subtitle="API identities for integrations — owned by a named person, never Admin, with expiring keys."
      showMetrics={false}
    >
      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-sm text-bad">
          {error}
        </p>
      )}

      {issued && (
        <div role="status" className="mb-4 rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm text-ink">
          <p className="font-semibold">New API key for {issued.accountName}</p>
          <p className="mt-1 text-xs text-muted">
            Copy it now and store it in your integration&apos;s secret store. It will not be shown again.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="break-all rounded bg-panel px-2 py-1 text-xs">{issued.key}</code>
            <button
              type="button"
              onClick={copyKey}
              className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs hover:bg-soft"
            >
              <Copy size={12} /> {copied ? "Copied" : "Copy"}
            </button>
            <button type="button" onClick={() => setIssued(null)} className="text-xs text-muted hover:underline">
              I&apos;ve stored it
            </button>
          </div>
          <p className="mt-2 text-xs text-muted">
            Send it as <code>Authorization: Bearer &lt;key&gt;</code>.
          </p>
        </div>
      )}

      <Card title="New service account" className="mb-4">
        <form onSubmit={handleCreate} className="grid grid-cols-1 gap-3 sm:grid-cols-4 items-end">
          <div>
            <label htmlFor="sa-name" className="mb-1.5 block text-xs font-medium text-muted">Name</label>
            <input
              id="sa-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="ERP nightly sync"
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div>
            <label htmlFor="sa-role" className="mb-1.5 block text-xs font-medium text-muted">Role</label>
            <select
              id="sa-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            >
              {SERVICE_ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="sa-owner" className="mb-1.5 block text-xs font-medium text-muted">Accountable owner</label>
            <select
              id="sa-owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            >
              {people.map((p) => (
                <option key={p.id} value={p.id}>{p.full_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="sa-description" className="mb-1.5 block text-xs font-medium text-muted">Purpose</label>
            <input
              id="sa-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What it connects to and why"
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div className="sm:col-span-4">
            <button
              type="submit"
              disabled={busy || !owner}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-2 disabled:opacity-60"
            >
              Create service account
            </button>
          </div>
        </form>
      </Card>

      {accounts.length === 0 ? (
        <Card title="Service accounts">
          <p className="text-sm text-muted">No service accounts yet.</p>
        </Card>
      ) : (
        accounts.map((account) => (
          <Card key={account.id} title={account.name} className="mb-4">
            <p className="mb-3 text-xs text-muted">
              {account.role} · owned by {account.owner_name}
              {account.description ? ` · ${account.description}` : ""}
            </p>
            {account.keys.length > 0 && (
              <table className="mb-3 w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] text-muted">
                    <th className="font-medium pb-2">Key</th>
                    <th className="font-medium pb-2">Created</th>
                    <th className="font-medium pb-2">Expires</th>
                    <th className="font-medium pb-2">Last used</th>
                    <th className="font-medium pb-2">Status</th>
                    <th className="font-medium pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {account.keys.map((key) => {
                    const status = keyStatus(key);
                    return (
                      <tr key={key.id} className="border-t border-line">
                        <td className="py-2"><code className="text-xs">{key.key_prefix}…</code></td>
                        <td className="py-2 text-xs text-muted">{day(key.created_at)}</td>
                        <td className="py-2 text-xs text-muted">{day(key.expires_at)}</td>
                        <td className="py-2 text-xs text-muted">{day(key.last_used_at)}</td>
                        <td className="py-2"><Pill tone={status.tone}>{status.label}</Pill></td>
                        <td className="py-2 text-right">
                          {status.label === "Active" && (
                            <button onClick={() => handleRevoke(account, key)} disabled={busy} className="text-xs text-bad hover:underline">
                              Revoke
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor={`sa-life-${account.id}`} className="text-xs text-muted">New key valid for</label>
              <select
                id={`sa-life-${account.id}`}
                value={lifetime[account.id] ?? 90}
                onChange={(e) => setLifetime((prev) => ({ ...prev, [account.id]: Number(e.target.value) }))}
                className="rounded-lg border border-line bg-soft px-2 py-1 text-sm text-ink outline-none focus:border-brand"
              >
                {KEY_LIFETIMES.map((d) => (
                  <option key={d} value={d}>{d} days</option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => handleIssue(account)}
                disabled={busy || !account.is_active}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink hover:bg-soft disabled:opacity-60"
              >
                <KeyRound size={14} /> {account.keys.some((k) => keyStatus(k).label === "Active") ? "Rotate: issue new key" : "Issue key"}
              </button>
            </div>
          </Card>
        ))
      )}
    </PageShell>
  );
}
