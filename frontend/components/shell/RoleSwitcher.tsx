"use client";

import { ROLES, RoleCode } from "@/lib/roles";
import { useRole } from "./RoleProvider";

export function RoleSwitcher() {
  const { role, realRole, canPreview, roleReady, setRole } = useRole();
  const previewing = role !== realRole;

  // Until the real role arrives the effective role is the fail-closed
  // Learner; showing it would flash "Learner" for an Admin.
  if (!roleReady) {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1.5 text-xs text-muted" aria-busy="true">
        <span className="hidden sm:inline">Role</span>
        <span className="inline-block h-3 w-14 animate-pulse rounded bg-soft" aria-label="Loading role" />
      </span>
    );
  }

  // Only an Admin (or a session-less demo) can switch; everyone else sees
  // their own role, read-only, instead of a menu that silently snaps back.
  if (!canPreview) {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1.5 text-xs text-muted">
        <span className="hidden sm:inline">Role</span>
        <span className="text-ink font-semibold">{realRole}</span>
      </span>
    );
  }

  return (
    <label
      className={`flex items-center gap-1.5 rounded-full border bg-panel pl-3 pr-2 py-1.5 text-xs text-muted ${
        previewing ? "border-brand" : "border-line"
      }`}
      title={previewing ? `Previewing the ${role} view. Your account is still ${realRole}.` : undefined}
    >
      <span className="sr-only">Viewing as role</span>
      <span className="hidden sm:inline">{previewing ? "Previewing as" : "Viewing as"}</span>
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as RoleCode)}
        aria-label="Viewing as role"
        className="bg-transparent text-ink font-semibold outline-none"
      >
        {(ROLES.includes(realRole) ? ROLES : [realRole, ...ROLES]).map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
    </label>
  );
}
