/**
 * Checks lib/roles.ts's effective-role gating — the rule that a provisioned
 * profile's role beats the demo zoiko_role cookie, and that everything else
 * falls back to demo mode exactly as before.
 *
 *   node lib/__tests__/role-gating.mjs
 *
 * Runs the real module (Node's TypeScript type-stripping), not a copy, so this
 * cannot silently drift from the source the way a reimplementation would.
 */

import {
  BACKEND_ROLES,
  DEFAULT_ROLE,
  ROLES,
  isKnownRole,
  resolveEffectiveRole,
} from "../roles.ts";

let failed = 0;
function check(label, condition, detail) {
  if (!condition) failed++;
  console.log(`${condition ? "PASS" : "FAIL"}  ${label}`);
  if (!condition && detail) console.log(`        ${detail}`);
}

// ── A real profile role always wins, including roles the demo switcher never lists ──
for (const role of BACKEND_ROLES) {
  check(
    `profile role "${role}" gates as itself (cookie ignored)`,
    resolveEffectiveRole(role, "CFO") === role,
    resolveEffectiveRole(role, "CFO")
  );
}

// ── Demo mode is unchanged: no profile → the cookie still rules ─────────────
check("no profile falls back to the cookie role", resolveEffectiveRole(null, "Tax Director") === "Tax Director");
check("undefined profile falls back to the cookie role", resolveEffectiveRole(undefined, "Learner") === "Learner");
check("default demo role is Admin", resolveEffectiveRole(null) === "Admin" && DEFAULT_ROLE === "Admin");

// ── A garbage / unrecognised profile role must not gate as garbage ──────────
check('unknown profile role "CEO" falls back, never gates as-is', resolveEffectiveRole("CEO", "CFO") === "CFO");
check('empty profile role falls back', resolveEffectiveRole("", "CFO") === "CFO");
check("isKnownRole rejects unknown roles", isKnownRole("CEO") === false);
check("isKnownRole accepts every backend role", BACKEND_ROLES.every(isKnownRole));

// ── Demo switcher vocabulary must not have been polluted by backend roles ───
check(
  "switcher ROLES list still offers only the 9 demo roles",
  ROLES.length === 9 && !ROLES.includes("Source Admin") && !ROLES.includes("System Auditor"),
  JSON.stringify(ROLES)
);

console.log(failed ? `\n${failed} FAILURE(S)` : "\nALL PASS");
process.exit(failed ? 1 : 0);