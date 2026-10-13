import { describe, expect, it } from "vitest";
import { ADULT_ONLY_MESSAGE, validateSignUp, type SignUpFields } from "@/services/auth.service";
import { BACKEND_ROLES, homePathFor } from "@/lib/roles";

const base: SignUpFields = {
  accountType: "company",
  firstName: "Asha",
  lastName: "Rao",
  email: "asha@example.com",
  companyName: "Acme",
  password: "Str0ngPass!",
  adultConfirmed: false,
};

describe("sign-up account type", () => {
  it("still requires a company name for company sign-up", () => {
    expect(validateSignUp({ ...base, companyName: "" }).companyName).toBeTruthy();
    expect(validateSignUp(base)).toEqual({});
  });

  it("does not ask an individual for a company name", () => {
    const errors = validateSignUp({ ...base, accountType: "individual", companyName: "", adultConfirmed: true });
    expect(errors).toEqual({});
  });

  it("requires individuals to confirm they are adults", () => {
    const errors = validateSignUp({ ...base, accountType: "individual", companyName: "" });
    expect(errors.adultConfirmed).toBe(ADULT_ONLY_MESSAGE);
  });
});

describe("role home", () => {
  it("lands Learners in their learning workspace and everyone else on the dashboard", () => {
    expect(homePathFor("Learner")).toBe("/learning-practice");
    expect(homePathFor("Admin")).toBe("/");
    expect(homePathFor(undefined)).toBe("/");
  });

  it("lets company Admins assign the Learner role", () => {
    expect(BACKEND_ROLES).toContain("Learner");
  });
});
