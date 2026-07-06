export type RoleCode =
  | "CFO"
  | "Controller"
  | "Audit Partner"
  | "Tax Director"
  | "Finance Manager"
  | "Business Owner"
  | "Learner"
  | "AI Governance Lead"
  | "Admin";

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

export const DEFAULT_ROLE: RoleCode = "Admin";

export const ROLE_COOKIE = "zoiko_role";
