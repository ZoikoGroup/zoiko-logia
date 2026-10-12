"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { BACKEND_ROLES } from "@/lib/roles";
import { useAuth } from "@/hooks/useAuth";
import { setImpersonation } from "@/lib/impersonation";
import {
  ApiError,
  createUser,
  getAuthToken,
  listUsers,
  resetUserMfa,
  setUserActive,
  setUserRole,
  startImpersonation,
  UserListItem,
} from "@/lib/api";

// Only roles the backend permission registry knows can be assigned; the demo
// personas (CFO, Controller, ...) would create accounts with no permissions.
const ASSIGNABLE_ROLES = BACKEND_ROLES;
const VIEW_AS_MINUTES = [15, 30, 60];

export default function UsersTeamsPage() {
  const { profile } = useAuth();
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [sendInvite, setSendInvite] = useState(true);
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>(ASSIGNABLE_ROLES[0]);

  const [viewAs, setViewAs] = useState<UserListItem | null>(null);
  const [viewAsReason, setViewAsReason] = useState("");
  const [viewAsMinutes, setViewAsMinutes] = useState(30);

  function loadUsers() {
    listUsers(getAuthToken())
      .then(setUsers)
      .catch((err) => {
        setError(
          err instanceof ApiError && err.status === 403
            ? "Admin role required to view users."
            : "Could not load users from the server."
        );
      });
  }

  useEffect(loadUsers, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setNotice("");
    setSubmitting(true);
    try {
      const created = await createUser(getAuthToken(), {
        email,
        full_name: fullName,
        role,
        ...(sendInvite ? {} : { password }),
      });
      setNotice(
        created.invited
          ? `Invitation sent to ${created.email}. They'll choose their own password from the email.`
          : `${created.full_name} was added. Share the temporary password with them securely.`,
      );
      setEmail("");
      setFullName("");
      setPassword("");
      loadUsers();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create user.");
    } finally {
      setSubmitting(false);
    }
  }

  async function runUserAction(userId: string, action: () => Promise<unknown>, done?: string) {
    setActionError("");
    setNotice("");
    setPendingUserId(userId);
    try {
      await action();
      if (done) setNotice(done);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not update the user.");
    } finally {
      setPendingUserId(null);
      loadUsers();
    }
  }

  function handleToggleActive(user: UserListItem) {
    return runUserAction(user.id, () => setUserActive(getAuthToken(), user.id, !user.is_active));
  }

  function handleRoleChange(user: UserListItem, nextRole: string) {
    if (nextRole === user.role) return;
    return runUserAction(user.id, () => setUserRole(getAuthToken(), user.id, nextRole));
  }

  function handleResetMfa(user: UserListItem) {
    if (!window.confirm(`Remove ${user.full_name}'s authenticator apps and sign them out everywhere?`)) return;
    return runUserAction(
      user.id,
      () => resetUserMfa(getAuthToken(), user.id),
      `${user.full_name}'s two-step verification was reset. They can sign in with their password and set it up again.`,
    );
  }

  async function handleStartViewAs(e: FormEvent) {
    e.preventDefault();
    if (!viewAs) return;
    setActionError("");
    try {
      const session = await startImpersonation(getAuthToken(), {
        target_user_id: viewAs.id,
        reason: viewAsReason,
        minutes: viewAsMinutes,
      });
      setImpersonation({
        sessionId: session.id,
        targetName: session.target_name,
        targetRole: session.target_role,
        expiresAt: session.expires_at,
      });
      // Full reload so navigation and every page re-render as the viewed user.
      window.location.assign("/");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not start viewing as this user.");
    }
  }

  return (
    <PageShell
      title="Users & Teams"
      subtitle="Manage user accounts, team membership, and role assignments."
      showMetrics={false}
    >
      <Card title="Add user" className="mb-4">
        <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div>
            <label htmlFor="new-user-name" className="block text-xs font-medium text-muted mb-1.5">Full name</label>
            <input
              id="new-user-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div>
            <label htmlFor="new-user-email" className="block text-xs font-medium text-muted mb-1.5">Email</label>
            <input
              id="new-user-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div>
            <label htmlFor="new-user-role" className="block text-xs font-medium text-muted mb-1.5">Role</label>
            <select
              id="new-user-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            >
              {ASSIGNABLE_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div>
            {sendInvite ? (
              <p className="text-xs text-muted pb-2">They&apos;ll get an email to choose their own password.</p>
            ) : (
              <>
                <label htmlFor="new-user-password" className="block text-xs font-medium text-muted mb-1.5">Temporary password</label>
                <input
                  id="new-user-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                />
              </>
            )}
          </div>
          <div className="sm:col-span-4 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-ink">
              <input
                type="checkbox"
                checked={sendInvite}
                onChange={(e) => setSendInvite(e.target.checked)}
                className="h-4 w-4 accent-brand"
              />
              Send invitation email (recommended)
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
            >
              {submitting ? "Adding..." : sendInvite ? "Send invitation" : "Add user"}
            </button>
            {formError && <p className="text-xs text-bad">{formError}</p>}
          </div>
        </form>
      </Card>

      {viewAs && (
        <Card title={`View as ${viewAs.full_name}`} className="mb-4">
          <form onSubmit={handleStartViewAs} className="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto_auto] gap-3 items-end">
            <div>
              <label htmlFor="view-as-reason" className="block text-xs font-medium text-muted mb-1.5">
                Reason (recorded in the audit log)
              </label>
              <input
                id="view-as-reason"
                value={viewAsReason}
                onChange={(e) => setViewAsReason(e.target.value)}
                required
                placeholder="e.g. Support ticket #1234 — user can't see Review Tasks"
                className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
              />
            </div>
            <div>
              <label htmlFor="view-as-minutes" className="block text-xs font-medium text-muted mb-1.5">For</label>
              <select
                id="view-as-minutes"
                value={viewAsMinutes}
                onChange={(e) => setViewAsMinutes(Number(e.target.value))}
                className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
              >
                {VIEW_AS_MINUTES.map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2">
              Start read-only view
            </button>
            <button
              type="button"
              onClick={() => setViewAs(null)}
              className="rounded-lg border border-line px-4 py-2 text-sm text-ink hover:bg-soft"
            >
              Cancel
            </button>
          </form>
          <p className="mt-2 text-xs text-muted">
            You&apos;ll see the workspace exactly as this user does. Nothing can be changed while viewing.
          </p>
        </Card>
      )}

      <Card title="Users">
        {error && <p className="text-xs text-bad mb-3">{error}</p>}
        {actionError && (
          <p role="alert" className="text-xs text-bad mb-3">
            {actionError}
          </p>
        )}
        {notice && (
          <p role="status" className="text-xs text-ok mb-3">
            {notice}
          </p>
        )}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Name</th>
              <th className="font-medium pb-2">Email</th>
              <th className="font-medium pb-2">Role</th>
              <th className="font-medium pb-2">Status</th>
              <th className="font-medium pb-2" />
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const isSelf = user.id === profile?.id;
              const busy = pendingUserId === user.id;
              const knownRole = (ASSIGNABLE_ROLES as readonly string[]).includes(user.role);
              return (
                <tr key={user.id} className="border-t border-line align-top">
                  <td className="py-2.5 font-semibold text-ink whitespace-nowrap">
                    {user.full_name}
                    {isSelf && <span className="ml-1.5 text-[11px] font-normal text-muted">(you)</span>}
                  </td>
                  <td className="py-2.5 text-ink">{user.email}</td>
                  <td className="py-2.5 text-ink">
                    {isSelf ? (
                      // The backend refuses self role changes; don't offer one.
                      user.role
                    ) : (
                      <select
                        aria-label={`Role for ${user.full_name}`}
                        value={user.role}
                        disabled={busy}
                        onChange={(e) => handleRoleChange(user, e.target.value)}
                        className="rounded-lg border border-line bg-soft px-2 py-1 text-sm text-ink outline-none focus:border-brand disabled:opacity-60"
                      >
                        {!knownRole && (
                          <option value={user.role} disabled>
                            {user.role} (no permissions)
                          </option>
                        )}
                        {ASSIGNABLE_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="py-2.5">
                    <Pill tone={user.is_active ? "ok" : "neutral"}>
                      {user.is_active ? "Active" : "Inactive"}
                    </Pill>
                  </td>
                  <td className="py-2.5 text-right whitespace-nowrap">
                    {!isSelf && (
                      <span className="inline-flex gap-3">
                        {user.is_active && user.role !== "Admin" && (
                          <button
                            onClick={() => {
                              setViewAs(user);
                              setViewAsReason("");
                            }}
                            disabled={busy}
                            className="text-xs text-brand hover:underline disabled:opacity-60"
                          >
                            View as
                          </button>
                        )}
                        <button
                          onClick={() => handleResetMfa(user)}
                          disabled={busy}
                          className="text-xs text-brand hover:underline disabled:opacity-60"
                        >
                          Reset MFA
                        </button>
                        <button
                          onClick={() => handleToggleActive(user)}
                          disabled={busy}
                          className="text-xs text-brand hover:underline disabled:opacity-60"
                        >
                          {user.is_active ? "Deactivate" : "Activate"}
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
