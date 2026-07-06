import { PageShell } from "@/components/governance/PageShell";
import { InfoCard } from "@/components/governance/InfoCard";
import { ONTOLOGY_CARDS } from "@/lib/governance-data";

const CARDS = ONTOLOGY_CARDS.filter((c) => c.heading !== "Professional bodies");

export default function AccountingOntologyPage() {
  return (
    <PageShell
      title="Accounting Ontology"
      subtitle="Manage the topic map, standards references, and risk/tool linkages behind Kriton's accounting knowledge graph."
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {CARDS.map((c) => (
          <InfoCard key={c.heading} heading={c.heading} body={c.body} />
        ))}
      </div>
    </PageShell>
  );
}
