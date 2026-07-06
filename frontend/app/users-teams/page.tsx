"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { ROLES, RoleCode } from "@/lib/roles";
import {
  ApiError,
  createUser,
  getAuthToken,
  listUsers,
  setUserActive,
  UserListItem,
} from "@/lib/api";

export default function UsersTeamsPage() {
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(ROLES[0]);

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
    setSubmitting(true);
    try {
      await createUser(getAuthToken(), { email, password, full_name: fullName, role });
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

  async function handleToggleActive(user: UserListItem) {
    await setUserActive(getAuthToken(), user.id, !user.is_active).catch(() => null);
    loadUsers();
  }

  return (
    <PageShell title="Users & Teams" subtitle="Manage user accounts, team membership, and role assignments.">
      <Card title="Add user" className="mb-4">
        <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Full name</label>
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as RoleCode)}
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-4">
            {formError && <p className="text-xs text-bad mb-2">{formError}</p>}
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
            >
              {submitting ? "Adding..." : "Add user"}
            </button>
          </div>
        </form>
      </Card>

      <Card title="Users">
        {error && <p className="text-xs text-bad mb-3">{error}</p>}
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
            {users.map((user) => (
              <tr key={user.id} className="border-t border-line align-top">
                <td className="py-2.5 font-semibold text-ink whitespace-nowrap">{user.full_name}</td>
                <td className="py-2.5 text-ink">{user.email}</td>
                <td className="py-2.5 text-ink">{user.role}</td>
                <td className="py-2.5">
                  <Pill tone={user.is_active ? "ok" : "neutral"}>
                    {user.is_active ? "Active" : "Inactive"}
                  </Pill>
                </td>
                <td className="py-2.5 text-right">
                  <button
                    onClick={() => handleToggleActive(user)}
                    className="text-xs text-brand hover:underline"
                  >
                    {user.is_active ? "Deactivate" : "Activate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
