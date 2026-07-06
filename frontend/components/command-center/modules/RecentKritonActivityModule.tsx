import { MessageSquare } from "lucide-react";
import { Card } from "@/components/governance/Card";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = [
  "CFO", "Controller", "Audit Partner", "Tax Director", "Finance Manager",
  "Business Owner", "Learner", "AI Governance Lead", "Admin",
];

const RECENT = [
  { question: "What is the VAT treatment for a mixed supply in the UK?", when: "12m ago" },
  { question: "Summarize the going-concern disclosure requirements under IFRS.", when: "1h ago" },
];

export function RecentKritonActivityModule() {
  return (
    <Card title="Recent Kriton Activity">
      <div className="space-y-3">
        {RECENT.map((item) => (
          <div key={item.question} className="flex items-start gap-2.5">
            <MessageSquare size={15} className="text-brand mt-0.5 shrink-0" />
            <div>
              <div className="text-sm text-ink">{item.question}</div>
              <div className="text-[11px] text-muted">{item.when}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
