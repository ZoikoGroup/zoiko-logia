import { describe, expect, it } from "vitest";

import { classifyAskKritonFailure, isRetryableAskKritonStatus } from "@/lib/ask-kriton-errors";

describe("classifyAskKritonFailure", () => {
  it("distinguishes the browser response deadline", () => {
    const error = new DOMException("aborted", "AbortError");
    expect(classifyAskKritonFailure(error, true)).toEqual({
      status: 408,
      message: "This request exceeded the two-minute response limit. Please try again.",
    });
  });

  it("reports an offline device before a generic network error", () => {
    expect(classifyAskKritonFailure(new TypeError("Failed to fetch"), false)?.message)
      .toContain("appears to be offline");
  });

  it("distinguishes network, authentication, capacity, and dependency failures", () => {
    expect(classifyAskKritonFailure(new TypeError("Failed to fetch"), true)?.message)
      .toContain("could not reach the service");
    expect(classifyAskKritonFailure({ status: 401 }, true)?.message)
      .toContain("session has expired");
    expect(classifyAskKritonFailure({ status: 429 }, true)?.message)
      .toContain("temporarily busy");
    expect(classifyAskKritonFailure({ status: 503 }, true)?.message)
      .toContain("data provider is temporarily unavailable");
  });

  it("preserves safe backend messages for expected non-server errors", () => {
    expect(classifyAskKritonFailure({ status: 422, message: "Please provide a reporting period." }, true))
      .toEqual({ status: 422, message: "Please provide a reporting period." });
  });

  it("uses generic copy for unclassified server errors", () => {
    expect(classifyAskKritonFailure({ status: 500, message: "internal detail" }, true)?.message)
      .toBe("Kriton encountered a temporary service problem. Please try again shortly.");
  });

  it("offers retry only for transient failures", () => {
    expect([0, 408, 429, 500, 502, 503, 504].every(isRetryableAskKritonStatus)).toBe(true);
    expect([400, 401, 403, 404, 422].some(isRetryableAskKritonStatus)).toBe(false);
  });
});
