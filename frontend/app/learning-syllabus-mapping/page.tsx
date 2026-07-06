import { PageShell } from "@/components/governance/PageShell";
import { InfoCard } from "@/components/governance/InfoCard";
import { PlannedModule } from "@/components/shell/PlannedModule";
import { ONTOLOGY_CARDS } from "@/lib/governance-data";

const CARD = ONTOLOGY_CARDS.find((c) => c.heading === "Professional bodies")!;

export default function LearningSyllabusMappingPage() {
  return (
    <PageShell
      title="Learning & Syllabus Mapping"
      subtitle="Map professional-body qualifications, pathways, and learning outcomes to Kriton's topic map."
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <InfoCard heading={CARD.heading} body={CARD.body} />
        <PlannedModule phase={3} description="Full syllabus-to-topic mapping editor, learning-outcome coverage, and reviewer sign-off workflow." />
      </div>
    </PageShell>
  );
}
