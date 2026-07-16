"use client";

import { ROLES, RoleCode } from "@/lib/roles";
import { useRole } from "./RoleProvider";

export function RoleSwitcher() {
  const { role, setRole } = useRole();

  return (
    <label className="flex h-10 items-center gap-2 rounded-xl border border-line bg-soft/60 px-3 text-xs">
      <span className="font-medium text-muted">Role</span>
      <span className="h-4 w-px bg-line" aria-hidden="true" />
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as RoleCode)}
        aria-label="Viewing as role"
        className="min-w-20 bg-transparent font-semibold text-ink outline-none"
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
    </label>
  );
}
