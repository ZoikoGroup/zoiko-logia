import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { Clock3, FileText, CheckSquare } from "lucide-react";

const RECENT_ACTIVITY = [
  { icon: FileText, label: "Saved answer — VAT treatment, mixed supply", when: "12m ago" },
  { icon: CheckSquare, label: "Completed review task — Atlas Financial Partners workpaper", when: "1h ago" },
  { icon: FileText, label: "Draft report started — Q2 compliance summary", when: "3h ago" },
];

const PENDING_TASKS = [
  { label: "Review Q2 workpaper — Meridian Health Group", status: "Due today" as const },
  { label: "Approve evidence pack — Atlas Financial Partners", status: "Due tomorrow" as const },
];

export default function MyWorkspacePage() {
  return (
    <main className="flex-1 overflow-y-auto p-4">
      <PageHeader title="My Workspace" subtitle="Your personal activity, pending tasks, and saved items in one place." />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card title="Recent Activity">
          <div className="space-y-3">
            {RECENT_ACTIVITY.map((item) => (
              <div key={item.label} className="flex items-start gap-2.5">
                <item.icon size={15} className="text-brand mt-0.5 shrink-0" />
                <div>
                  <div className="text-sm text-ink">{item.label}</div>
                  <div className="text-[11px] text-muted flex items-center gap-1">
                    <Clock3 size={11} /> {item.when}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Pending Tasks">
          <div className="space-y-3">
            {PENDING_TASKS.map((task) => (
              <div key={task.label} className="flex items-center justify-between gap-2">
                <span className="text-sm text-ink">{task.label}</span>
                <Pill tone="warn">{task.status}</Pill>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </main>
  );
}
