import { describe, expect, it } from "vitest";
import { workflowPositions } from "@/components/visualization/X6Flow";

describe("workflow layout", () => {
  // QA cases E01, E03, E04: eight stages in one row were shrunk to half size.
  it("wraps stages into rows that fit the container at full size", () => {
    const positions = workflowPositions(8, 940);
    const right = Math.max(...positions.map((p) => p.x)) + 150;
    expect(right).toBeLessThanOrEqual(940 - 48);
    expect(new Set(positions.map((p) => p.y)).size).toBeGreaterThan(1);
  });

  it("runs every other row backwards so each arrow stays short", () => {
    const positions = workflowPositions(8, 940);
    const perRow = positions.filter((p) => p.y === positions[0].y).length;
    // The first stage of row two sits directly below the last stage of row one.
    expect(positions[perRow].x).toBe(positions[perRow - 1].x);
    expect(positions[perRow + 1].x).toBeLessThan(positions[perRow].x);
  });

  it("keeps one stage per row in a very narrow container", () => {
    const positions = workflowPositions(3, 200);
    expect(positions.map((p) => p.x)).toEqual([24, 24, 24]);
  });
});
