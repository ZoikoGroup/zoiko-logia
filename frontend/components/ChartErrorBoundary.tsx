"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { emitVisualizationEvent } from "@/lib/telemetry";
import type { SelectionSource } from "@/lib/api";

type Props = {
  children: ReactNode;
  title: string;
  // Dynamic Visualization Selection v4 telemetry — deliberately just chart
  // *metadata* (a type name, an intent label, opaque ids), never the chart's
  // categories/series/title or anything derived from the error itself
  // (message/stack/componentStack are read in componentDidCatch but never
  // forwarded anywhere).
  telemetry?: {
    conversationId?: string | null;
    queryId?: string | null;
    analyticalIntent?: string | null;
    originalChartType?: string | null;
    activeChartType?: string | null;
    selectionSource?: SelectionSource | null;
    renderer?: string | null;
    schemaVersion?: string | null;
  };
};
type State = { hasError: boolean };

/** React error boundaries must be class components — there is no hook
 * equivalent. Scoped to one chart's render so a single malformed or
 * unexpectedly-shaped chart (e.g. a stale saved payload, or a divide-by-zero
 * in a client-side data transform like buildSlopeData) shows an inline
 * message instead of blanking the rest of the answer, including the other
 * charts, guides, and follow-ups rendered alongside it. */
export class ChartErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(): void {
    // No second argument (errorInfo) read here, and the caught error object
    // itself is never touched — this handler only ever forwards the chart
    // metadata already passed in via props, never the error's message,
    // stack, or componentStack.
    const telemetry = this.props.telemetry;
    emitVisualizationEvent({
      event_name: "visualization_render_failed",
      conversation_id: telemetry?.conversationId,
      query_id: telemetry?.queryId,
      analytical_intent: telemetry?.analyticalIntent,
      original_chart_type: telemetry?.originalChartType,
      active_chart_type: telemetry?.activeChartType,
      selection_source: telemetry?.selectionSource,
      renderer: telemetry?.renderer,
      schema_version: telemetry?.schemaVersion,
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="flex h-[300px] w-full flex-col items-center justify-center gap-2 p-4 text-center text-xs text-muted"
        >
          <AlertTriangle size={20} className="text-warn" aria-hidden="true" />
          <p>
            <span className="font-semibold text-ink">{this.props.title}</span> couldn&apos;t be displayed.
          </p>
          <p>The validated data is still shown in the table above.</p>
        </div>
      );
    }
    return this.props.children;
  }
}
