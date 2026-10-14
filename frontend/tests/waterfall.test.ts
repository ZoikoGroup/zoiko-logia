import { describe, expect, it } from "vitest";
import { waterfallSteps, waterfallSeries } from "@/lib/waterfall";

describe("waterfalls across zero", () => {
  it("preserves signed endpoints and draws the final negative total from zero", () => {
    expect(waterfallSteps([40000, 25000, -38000, -12000, -20000, -5000])).toEqual([
      { start: 0, end: 40000, value: 40000, total: true },
      { start: 40000, end: 65000, value: 25000, total: false },
      { start: 65000, end: 27000, value: -38000, total: false },
      { start: 27000, end: 15000, value: -12000, total: false },
      { start: 15000, end: -5000, value: -20000, total: false },
      { start: 0, end: -5000, value: -5000, total: true },
    ]);
  });
  it("uses correct pixel geometry for a bar crossing zero", () => {
    const series = waterfallSeries([10,-15,-5], { up: "green", down: "red", total: "blue", ink: "black" });
    const output = series.renderItem({ dataIndex: 1 }, { coord: ([x,y]) => [x*100,100-y*2], size: () => [100,0] });
    expect(output.children[0]).toMatchObject({ type: "rect", shape: { x: 73, y: 80, width: 54, height: 30 }, style: { fill: "red" } });
    expect(series.data.at(-1)).toEqual([2,0,-5]);
  });
  it("supports negative opening balances and recovery above zero", () => {
    expect(waterfallSteps([-10,25,15]).map(({start,end}) => [start,end])).toEqual([[0,-10],[-10,15],[0,15]]);
  });
});
