import { describe, expect, it, vi, beforeEach } from "vitest";
import type ReactECharts from "echarts-for-react";
import { exportEChartPng } from "@/lib/export/exportEChartPng";

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
});

function fakeChartRef(getDataURL: ReturnType<typeof vi.fn>) {
  return {
    current: { getEchartsInstance: () => ({ getDataURL }) },
  } as unknown as React.RefObject<ReactECharts | null>;
}

describe("exportEChartPng", () => {
  it("reads the PNG from the chart instance actually attached to the ref", () => {
    const getDataURL = vi.fn(() => "data:image/png;base64,AAAA");
    const ref = fakeChartRef(getDataURL);

    const ok = exportEChartPng(ref, "Current ratio trend");

    expect(ok).toBe(true);
    expect(getDataURL).toHaveBeenCalledWith(
      expect.objectContaining({ type: "png", pixelRatio: 2 }),
    );
  });

  it("returns false without throwing when no chart instance is mounted", () => {
    const ref = { current: null } as React.RefObject<ReactECharts | null>;
    expect(exportEChartPng(ref, "title")).toBe(false);
  });
});
