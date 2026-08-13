import type { ReactNode } from "react";
import type { VisualizationSpec } from "@/lib/api";

/**
 * Plain-HTML tabular view of whatever real data a chart spec carries — the
 * one accessible-fallback/power-user-data-access representation shared by
 * three call sites: the error boundary, the always-available "View as
 * table" toggle, and the structurally-invalid state. Never re-derives
 * numbers; each branch just re-labels the SAME fields the chart itself
 * reads.
 */
export function DataTableView({ viz }: { viz: VisualizationSpec }) {
  const th = "border border-line px-3 py-2 font-semibold text-ink";
  const td = "border border-line px-3 py-2 align-top text-ink";

  if (viz.type === "LINE" || viz.type === "BAR") {
    return (
      <Table>
        <thead><tr><th className={th}>Period</th><th className={th}>{viz.title ?? "Value"}</th></tr></thead>
        <tbody>
          {viz.data.map((p, i) => (
            <tr key={i}><td className={td}>{p.x}</td><td className={td}>{p.y.toLocaleString()}</td></tr>
          ))}
        </tbody>
      </Table>
    );
  }

  if (viz.type === "HISTOGRAM") {
    return (
      <Table>
        <thead><tr><th className={th}>Bin</th><th className={th}>Count</th></tr></thead>
        <tbody>
          {viz.data.map((p, i) => (
            <tr key={i}><td className={td}>{p.x}</td><td className={td}>{p.y}</td></tr>
          ))}
        </tbody>
      </Table>
    );
  }

  if (viz.type === "BOX" && viz.box) {
    const rows: [string, number][] = [
      ["Minimum", viz.box.minimum], ["Q1", viz.box.q1], ["Median", viz.box.median],
      ["Q3", viz.box.q3], ["Maximum", viz.box.maximum],
    ];
    return (
      <div>
        <Table>
          <thead><tr><th className={th}>Statistic</th><th className={th}>Value</th></tr></thead>
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label}><td className={td}>{label}</td><td className={td}>{value.toLocaleString()}</td></tr>
            ))}
          </tbody>
        </Table>
        {viz.box.outliers.length > 0 && (
          <p className="mt-2 text-xs text-muted">Outliers: {viz.box.outliers.map((v) => v.toLocaleString()).join(", ")}</p>
        )}
      </div>
    );
  }

  if (viz.type === "SCATTER") {
    const xLabel = viz.encoding?.x.field ?? "X";
    const yLabel = viz.encoding?.y.field ?? "Y";
    return (
      <Table>
        <thead><tr><th className={th}>Period</th><th className={th}>{xLabel}</th><th className={th}>{yLabel}</th></tr></thead>
        <tbody>
          {viz.scatter.map((p, i) => (
            <tr key={i}><td className={td}>{p.label}</td><td className={td}>{p.x.toLocaleString()}</td><td className={td}>{p.y.toLocaleString()}</td></tr>
          ))}
        </tbody>
      </Table>
    );
  }

  if (viz.type === "HEATMAP") {
    return (
      <Table>
        <thead><tr><th className={th}>Source</th><th className={th}>Target</th><th className={th}>Value</th></tr></thead>
        <tbody>
          {viz.cells.map((c, i) => (
            <tr key={i}><td className={td}>{c.x}</td><td className={td}>{c.y}</td><td className={td}>{c.value.toLocaleString()}</td></tr>
          ))}
        </tbody>
      </Table>
    );
  }

  if (viz.type === "DONUT") {
    return (
      <Table>
        <thead><tr><th className={th}>Holder</th><th className={th}>Share (%)</th><th className={th}>Estimated</th></tr></thead>
        <tbody>
          {viz.donut.map((s, i) => (
            <tr key={i}>
              <td className={td}>{s.label}</td>
              <td className={td}>{s.value.toLocaleString()}</td>
              <td className={td}>{s.is_estimated ? "Yes (band midpoint)" : "No"}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    );
  }

  return <p className="text-xs text-muted">No tabular representation available for this visualization.</p>;
}

function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">{children}</table>
    </div>
  );
}
