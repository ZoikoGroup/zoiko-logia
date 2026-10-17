import { describe, expect, it } from "vitest";
import { NAV_SECTIONS, canAccessPath, isVisible, navHref } from "@/lib/nav";
import { BACKEND_ROLES, signInHomeFor, type RoleCode } from "@/lib/roles";

// The sidebar filters sections before items, so an item a role may open is
// unreachable unless its section admits that role too. This is how the SME
// Reviewer once ended up with an empty sidebar.
describe("sidebar role gating", () => {
  it("never grants an item to a role its section hides", () => {
    for (const section of NAV_SECTIONS) {
      for (const item of section.items) {
        for (const role of item.allowedRoles) {
          expect(isVisible(section.allowedRoles, role), `${role} → ${section.label} / ${item.label}`).toBe(true);
        }
      }
    }
  });

  it("gives every backend role at least one page", () => {
    for (const role of BACKEND_ROLES as readonly RoleCode[]) {
      const visible = NAV_SECTIONS.filter((s) => isVisible(s.allowedRoles, role)).flatMap((s) =>
        s.items.filter((i) => isVisible(i.allowedRoles, role)),
      );
      expect(visible.length, role).toBeGreaterThan(0);
    }
  });

  it("shows the SME Reviewer the review queue", () => {
    const reviewTasks = NAV_SECTIONS.flatMap((s) =>
      isVisible(s.allowedRoles, "SME Reviewer") ? s.items : [],
    ).find((i) => i.slug === "review-tasks");
    expect(reviewTasks && isVisible(reviewTasks.allowedRoles, "SME Reviewer")).toBe(true);
  });
});

describe("typed-URL route gating", () => {
  it("keeps a Learner to the learning pages", () => {
    for (const path of ["/learning-practice", "/ask-kriton", "/my-workspace", "/account/security"]) {
      expect(canAccessPath(path, "Learner"), path).toBe(true);
    }
    for (const path of ["/users-teams", "/tenant-settings", "/source-library/tax", "/overview/governance", "/drafts-reports"]) {
      expect(canAccessPath(path, "Learner"), path).toBe(false);
    }
  });

  it("lets an Admin open every page", () => {
    for (const section of NAV_SECTIONS) {
      for (const item of section.items) {
        expect(canAccessPath(navHref(item.slug), "Admin"), item.label).toBe(true);
      }
    }
  });
});

describe("sign-in landing page", () => {
  it("sends each kind of account to its own home", () => {
    expect(signInHomeFor({ role: "Admin" })).toBe("/");
    expect(signInHomeFor({ role: "Learner" })).toBe("/learning-practice");
    expect(signInHomeFor({ role: "Admin", platform_role: "super_admin" })).toBe("/super-admin");
  });
});
