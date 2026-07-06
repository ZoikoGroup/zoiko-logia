import { ReactNode } from "react";
import { PageHeader } from "./PageHeader";
import { MetricsRow } from "./MetricsRow";
import { FooterNote } from "./FooterNote";

export function PageShell({
  title, subtitle, children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <main className="flex-1 overflow-y-auto p-4 pt-0">
      <PageHeader title={title} subtitle={subtitle} />
      <MetricsRow />
      {children}
      <FooterNote />
    </main>
  );
}
