import { describe, expect, it } from "vitest";
import { errorText } from "@/lib/api";

describe("errorText", () => {
  it("reads a validation error list instead of showing [object Object]", () => {
    const detail = [{ loc: ["body", "previous_query"], msg: "String should have at most 2000 characters", type: "string_too_long" }];
    expect(errorText(detail)).toBe("The request was not accepted: String should have at most 2000 characters");
  });

  it("keeps a plain message and reads a structured one", () => {
    expect(errorText("Not allowed")).toBe("Not allowed");
    expect(errorText({ code: "X", message: "Engagement required" })).toBe("Engagement required");
    expect(errorText(undefined)).toBeUndefined();
    expect(errorText({ code: "X" })).toBeUndefined();
  });
});
