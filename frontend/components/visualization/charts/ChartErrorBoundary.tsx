"use client";

import { Component, type ReactNode } from "react";
import type { VisualizationSpec } from "@/lib/api";
import { trackVisualizationInteraction } from "@/lib/telemetry";
import { DataTableView } from "./DataTableView";

/**
 * Wraps a single chart instance so a malformed/throwing render never takes
 * down the rest of the answer (mirrors GraphErrorBoundary's pattern — a
 * class component because catching render-time errors needs
 * getDerivedStateFromError, which has no hook equivalent). Falls back to a
 * plain data table, which can't itself fail the way a canvas renderer can.
 */
export class ChartErrorBoundary extends Component<
  { viz: VisualizationSpec; renderer: string; children: ReactNode; onError?: () => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError?.();
    trackVisualizationInteraction("render_failed", "chart", {
      visualizationId: this.props.viz.id,
      visualizationType: this.props.viz.type,
      renderer: this.props.renderer,
    });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div>
        <p className="mb-2 text-xs leading-5 text-muted">
          This chart could not be displayed. The underlying data is available below.
        </p>
        <DataTableView viz={this.props.viz} />
      </div>
    );
  }
}
