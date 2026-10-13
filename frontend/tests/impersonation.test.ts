import { afterEach, describe, expect, it } from "vitest";
import {
  clearImpersonation,
  getImpersonation,
  impersonationHeaders,
  setImpersonation,
} from "@/lib/impersonation";

const inAnHour = () => new Date(Date.now() + 60 * 60 * 1000).toISOString();

describe("impersonation session state", () => {
  afterEach(() => clearImpersonation());

  it("sends no header when nobody is being viewed", () => {
    expect(impersonationHeaders()).toEqual({});
  });

  it("attaches the session to every call while viewing", () => {
    setImpersonation({ sessionId: "s-1", targetName: "Grace", targetRole: "SME Reviewer", expiresAt: inAnHour() });
    expect(impersonationHeaders()).toEqual({ "X-Impersonation-Session": "s-1" });
    expect(getImpersonation()?.targetName).toBe("Grace");
  });

  it("drops an expired session instead of sending it", () => {
    setImpersonation({
      sessionId: "s-old", targetName: "Grace", targetRole: "SME Reviewer",
      expiresAt: new Date(Date.now() - 1000).toISOString(),
    });
    expect(impersonationHeaders()).toEqual({});
    expect(getImpersonation()).toBeNull();
  });

  it("notifies listeners when the session starts and ends", () => {
    let changes = 0;
    const listener = () => changes++;
    window.addEventListener("zoiko-impersonation-change", listener);
    setImpersonation({ sessionId: "s-2", targetName: "A", targetRole: "Risk Admin", expiresAt: inAnHour() });
    clearImpersonation();
    window.removeEventListener("zoiko-impersonation-change", listener);
    expect(changes).toBe(2);
  });
});
