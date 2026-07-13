import { ReactNode } from "react";
import { PageHeader } from "./PageHeader";
import { MetricsRow } from "./MetricsRow";

export function PageShell({
  title, subtitle, children, showMetrics = true,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  showMetrics?: boolean;
}) {
  return (
    <main className="flex-1 overflow-y-auto p-4">
      <PageHeader title={title} subtitle={subtitle} />
      {showMetrics && <MetricsRow />}
      {children}
    </main>
  );
}
