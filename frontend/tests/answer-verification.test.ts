import { describe, expect, it } from "vitest";
import type { VerificationBreakdown } from "@/lib/api";
import { verificationSummary, verifiedLabel } from "@/lib/answer-state";

const v = (over: Partial<VerificationBreakdown>): VerificationBreakdown => ({
  arithmetic: "not_applicable", sources: "not_applicable", assumptions: "not_applicable", overall: "fully_verified", ...over,
});

// Correct arithmetic, or one citation, is not proof of the whole answer (24 Oct 2026).
describe("the answer label says what was verified", () => {
  it("keeps the label of a fully verified answer", () => {
    expect(verifiedLabel("Answered — calculated and verified", v({ arithmetic: "verified", assumptions: "confirmed" })))
      .toBe("Answered — calculated and verified");
    expect(verifiedLabel("Answered — source grounded", v({ sources: "verified" }))).toBe("Answered — source grounded");
  });

  it("does not call a calculation verified when its assumptions are not confirmed", () => {
    const quarter = v({ arithmetic: "verified", assumptions: "stated", overall: "partially_verified" });
    expect(verifiedLabel("Answered — calculated and verified", quarter))
      .toBe("Answered — arithmetic verified, assumptions not confirmed");
    expect(verificationSummary(quarter)).toBe("Arithmetic: verified · Assumptions: stated, not confirmed");
  });

  it("does not call a partly sourced answer source grounded", () => {
    const partly = v({ sources: "partial", overall: "partially_verified" });
    expect(verifiedLabel("Answered — source grounded", partly)).toBe("Answered — partly source-verified");
    expect(verificationSummary(partly)).toBe("Sources: partly verified");
  });

  it("names a figure that differs from the calculation", () => {
    const mismatch = v({ arithmetic: "mismatch", sources: "partial", assumptions: "stated", overall: "partially_verified" });
    expect(verifiedLabel("Answered — source grounded", mismatch)).toBe("Answered — a figure differs from the calculation");
    expect(verificationSummary(mismatch))
      .toBe("Arithmetic: a figure differs from the calculation · Sources: partly verified · Assumptions: stated, not confirmed");
  });

  it("leaves partial, unanswered and older answers as they were", () => {
    expect(verifiedLabel("Partially answered — some parts incomplete", v({ overall: "partially_verified" })))
      .toBe("Partially answered — some parts incomplete");
    expect(verifiedLabel("Answered — source grounded", null)).toBe("Answered — source grounded");
    expect(verificationSummary(undefined)).toBeNull();
  });
});

// Four US GAAP answers had correct sums and the wrong treatment, and a
// withheld answer still showed "Arithmetic: verified" (25 Oct 2026).
describe("arithmetic is not reported as verifying the accounting treatment", () => {
  it("says the treatment is not verified when only the arithmetic is", () => {
    const lease = v({ arithmetic: "verified", treatment: "not_verified", overall: "partially_verified" });
    expect(verifiedLabel("Answered — calculated and verified", lease))
      .toBe("Answered — arithmetic verified; accounting treatment not verified");
    expect(verificationSummary(lease)).toBe("Arithmetic: verified · Accounting treatment: not verified");
  });

  it("says a treatment finding needs review", () => {
    const flagged = v({ arithmetic: "verified", treatment: "issue_found", overall: "partially_verified" });
    expect(verifiedLabel("Answered — calculated and verified", flagged))
      .toBe("Answered — arithmetic verified; accounting treatment not verified");
    expect(verificationSummary(flagged)).toBe("Arithmetic: verified · Accounting treatment: needs review");
  });

  it("names a cited treatment without claiming the source proves it", () => {
    const sourced = v({ sources: "verified", treatment: "cited_checks_passed", overall: "partially_verified" });
    expect(verifiedLabel("Answered — source grounded", sourced)).toBe("Answered — source grounded");
    expect(verificationSummary(sourced)).toBe("Sources: verified · Accounting treatment: cited; evidence checks passed");
  });

  // "Cited; evidence checks passed" must never become "treatment verified" (review, 25 Oct 2026).
  it("never calls a cited treatment verified in the headline", () => {
    const cited = v({ arithmetic: "verified", sources: "verified", treatment: "cited_checks_passed",
                      overall: "partially_verified" });
    expect(verifiedLabel("Answered — calculated and verified", cited))
      .toBe("Answered — arithmetic verified; accounting treatment not verified");
    for (const treatment of ["cited_checks_passed", "not_verified", "issue_found"] as const) {
      const text = verificationSummary(v({ arithmetic: "verified", treatment })) ?? "";
      expect(text).not.toMatch(/treatment: verified|treatment verified/i);
    }
  });

  it("reads answers recorded before the treatment field as before", () => {
    expect(verificationSummary(v({ arithmetic: "verified" }))).toBe("Arithmetic: verified");
  });

  it("never relabels an unanswered response", () => {
    const withheld = v({ treatment: "not_verified", overall: "not_verified" });
    expect(verifiedLabel("Not answered — insufficient evidence", withheld)).toBe("Not answered — insufficient evidence");
  });
});
