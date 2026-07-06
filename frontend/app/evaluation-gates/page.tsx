import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { EVAL_GATES, EVAL_CAPTION } from "@/lib/governance-data";

const TONE_TEXT: Record<string, string> = { ok: "text-ok", warn: "text-warn" };

export default function EvaluationGatesPage() {
  return (
    <PageShell
      title="Evaluation Gates"
      subtitle="Review QA, red-team, citation, hallucination, refusal, multilingual, and source-conflict results."
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {EVAL_GATES.map((g) => (
          <Card key={g.label}>
            <div className="text-xs text-muted">{g.label}</div>
            <div className={`mt-1 text-2xl font-extrabold tracking-tight ${TONE_TEXT[g.tone]}`}>{g.value}</div>
            <p className="mt-2 text-xs text-muted leading-relaxed">{EVAL_CAPTION}</p>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}
