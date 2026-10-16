import { ReactNode } from "react";
import { PageHeader } from "./PageHeader";

export function PageShell({
  title, subtitle, children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  const governed = ["Source Library", "Source Bundles", "Accounting Ontology", "Jurisdiction Rollout", "Risk Policy", "Evaluation Gates", "Model & Prompt Registry"].includes(title);
  const family = ["Risk Policy", "Evaluation Gates", "Model & Prompt Registry"].includes(title) ? "AI Governance" : "Source & Knowledge Governance";
  return (
    <main className={`flex-1 overflow-y-auto p-4 ${governed ? "overview-page lg:p-6" : ""}`}>
      <div className={governed ? "mx-auto max-w-[1600px] space-y-4" : ""}>
      {governed && <div className="text-[10px] text-muted">Workspace / {family} / <b className="text-ink">{title}</b></div>}
      {governed ? <header><p className="text-[9px] font-bold uppercase tracking-[.14em] text-amber-700">{family}</p><h1 className="mt-1 text-[28px] font-bold tracking-tight text-ink">{title}</h1><p className="mt-1 text-xs leading-5 text-muted">{subtitle}</p></header> : <PageHeader title={title} subtitle={subtitle} />}
      {children}
      </div>
    </main>
  );
}
