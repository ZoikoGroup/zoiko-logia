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

it("component failures override an inconsistent fully-verified aggregate", () => {
  expect(verifiedLabel("Answered — calculated and verified", v({ arithmetic: "mismatch", sources: "unsupported" })))
    .toBe("Answered — a figure differs from the calculation");
});

it("unsupported citations do not produce a source-grounded label", () => {
  expect(verifiedLabel("Answered — source grounded", v({ sources: "unsupported", overall: "not_verified" })))
    .toBe("Answered — sources not verified");
});

it("unknown status values cannot produce undefined verification copy", () => {
  const unknown = { arithmetic: "unknown", sources: "unknown", assumptions: "stated", overall: "fully_verified" } as unknown as VerificationBreakdown;
  expect(verifiedLabel("Answered — calculated and verified", unknown)).not.toBe("Answered — calculated and verified");
  expect(verificationSummary(unknown)).not.toContain("undefined");
});
