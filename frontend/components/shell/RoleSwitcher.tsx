"use client";

import { ROLES, RoleCode } from "@/lib/roles";
import { useRole } from "./RoleProvider";

export function RoleSwitcher() {
  const { role, setRole } = useRole();

  return (
    <label className="flex items-center gap-1.5 rounded-full border border-line bg-panel pl-3 pr-2 py-1.5 text-xs text-muted">
      <span className="sr-only">Viewing as role</span>
      <span className="hidden sm:inline">Viewing as</span>
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as RoleCode)}
        aria-label="Viewing as role"
        className="bg-transparent text-ink font-semibold outline-none"
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
