export type RoleCode =
  // Demo-mode vocabulary the RoleSwitcher/zoiko_role cookie speaks (a preview
  // of the wider enterprise roles the product is heading toward).
  | "CFO"
  | "Controller"
  | "Audit Partner"
  | "Tax Director"
  | "Finance Manager"
  | "Business Owner"
  | "Learner"
  | "AI Governance Lead"
  | "Admin"
  // Real backend RBAC roles — what /auth/me (profile.role) actually returns.
  // These come from scripts/seed_dev_user.py's ROLES plus the "Admin" default
  // that POST /auth/provision assigns. They are NOT offered by the demo
  // switcher; they are the values the app gates on once a profile exists.
  | "Governance Ops Lead"
  | "Source Admin"
  | "Syllabus Admin"
  | "Jurisdiction Lead"
  | "Risk Admin"
  | "System Auditor";

export const ROLES: RoleCode[] = [
  "CFO",
  "Controller",
  "Audit Partner",
  "Tax Director",
  "Finance Manager",
  "Business Owner",
  "Learner",
  "AI Governance Lead",
  "Admin",
];

// Roles a verified profile can actually be. The demo switcher must stay a
// demo: it offers only the enterprise subset above, and a profile role like
// "Source Admin" is still a legitimate *gating* value even though the switcher
// never lists it.
export const BACKEND_ROLES: readonly string[] = [
  "Admin",
  "Governance Ops Lead",
  "Source Admin",
  "Syllabus Admin",
  "Jurisdiction Lead",
  "Risk Admin",
  "System Auditor",
];

export const DEFAULT_ROLE: RoleCode = "Admin";

export const ROLE_COOKIE = "zoiko_role";

const KNOWN_ROLES: ReadonlySet<string> = new Set([...ROLES, ...BACKEND_ROLES]);

export function isKnownRole(role: string | null | undefined): role is RoleCode {
  return typeof role === "string" && KNOWN_ROLES.has(role);
}

/** The role the app actually gates on: the provisioned profile's role when a
 * real one exists, otherwise the demo-mode cookie role (so unauthenticated /
 * not-yet-provisioned previews keep working exactly as before). */
export function resolveEffectiveRole(
  profileRole: string | null | undefined,
  demoRole: RoleCode = DEFAULT_ROLE,
): RoleCode {
  if (typeof profileRole === "string" && KNOWN_ROLES.has(profileRole)) {
    return profileRole as RoleCode;
  }
  return demoRole;
}
