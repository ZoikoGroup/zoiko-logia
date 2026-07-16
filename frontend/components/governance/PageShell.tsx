import { ReactNode } from "react";
import { MetricsRow } from "./MetricsRow";

export function PageShell({
  children, showMetrics = true,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  showMetrics?: boolean;
}) {
  return (
    <main className="flex-1 overflow-y-auto p-4">
      {showMetrics && <MetricsRow />}
      {children}
    </main>
  );
}
