import type ReactECharts from "echarts-for-react";
import { dataUrlToBlob, downloadBlob, sanitizeFilename } from "@/lib/visualizationExport";

/** Uses ECharts' own image-export capability (getDataURL) rather than a
 * generic screenshot library — it renders straight from the chart's live
 * option/data, at a pixel ratio suited to a printed report, and includes
 * whatever title/legend/labels are currently visible. */
export function exportEChartPng(
  chartRef: React.RefObject<ReactECharts | null>,
  title: string,
): boolean {
  const blob = echartToPngBlob(chartRef);
  if (!blob) return false;
  downloadBlob(blob, sanitizeFilename(title, "png"));
  return true;
}

/** The same PNG the download produces, as a Blob, for "Copy image". Kept
 * beside the download so both stay on one set of export settings. */
export function echartToPngBlob(
  chartRef: React.RefObject<ReactECharts | null>,
): Blob | null {
  const instance = chartRef.current?.getEchartsInstance();
  if (!instance) return null;
  const dataUrl = instance.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
  return dataUrlToBlob(dataUrl);
}
