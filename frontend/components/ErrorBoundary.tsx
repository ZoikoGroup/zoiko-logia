"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

/**
 * Contains a render failure to one part of the page.
 *
 * app/error.tsx already catches everything, but it replaces the entire route —
 * one malformed chart spec in the fourth answer of a conversation would take
 * the whole thread with it. Wrapping the answer body instead means a bad
 * render costs you that answer's formatting and nothing else: the question,
 * the sources, the actions and every other turn stay usable.
 *
 * Must be a class component — React has no hook equivalent for
 * componentDidCatch.
 */
type Props = {
  children: ReactNode;
  /** Shown in place of the children when they throw. */
  fallback?: ReactNode;
  /** Label for the console entry, so a report says which surface failed. */
  label?: string;
};

type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Render error in ${this.props.label ?? "component"}:`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    return (
      <div className="my-3 flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/5 p-3 text-xs leading-5 text-bad">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <span>
          This part of the response could not be displayed.
          {this.state.error.message ? ` (${this.state.error.message})` : ""}
        </span>
      </div>
    );
  }
}
