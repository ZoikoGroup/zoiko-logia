"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

/**
 * Route-level error boundary. Without one, a single render exception blanks the
 * whole app with no recovery — and this product renders model-generated Mermaid
 * diagrams and JSON chart specs, which are exactly the kind of input that can
 * throw during render.
 *
 * Deliberately shows the error message: this is an internal governance tool,
 * and an operator who can see "Cannot read properties of undefined" can act on
 * it, where "Something went wrong" leaves them with nothing to report.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Kept so a crash leaves a trace in the browser console even when the
    // overlay is dismissed. Swap for a real reporter when one exists.
    console.error("Unhandled render error:", error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg p-6 text-ink">
      <div className="w-full max-w-lg rounded-2xl border border-bad/30 bg-panel p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <AlertTriangle size={18} className="text-bad" />
          <h1 className="text-lg font-bold">Something broke while rendering this page</h1>
        </div>

        <p className="mt-3 text-sm leading-6 text-muted">
          The page failed to render. Your conversations are stored locally and have not been lost —
          retrying usually recovers.
        </p>

        <pre className="mt-4 max-h-40 overflow-auto rounded-lg border border-line bg-soft p-3 text-xs leading-5 text-ink">
          {error.message || "Unknown error"}
          {error.digest ? `\n\nDigest: ${error.digest}` : ""}
        </pre>

        <button
          type="button"
          onClick={reset}
          className="mt-5 inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-bold text-panel transition hover:bg-brand"
        >
          <RotateCcw size={15} />
          Try again
        </button>
      </div>
    </main>
  );
}
