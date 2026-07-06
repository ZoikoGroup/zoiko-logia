import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { COMPLIANCE_CALENDAR } from "@/lib/governance-data";

const STATUS_TONE: Record<string, "info" | "warn" | "bad"> = {
  Upcoming: "info",
  "At risk": "warn",
  Overdue: "bad",
};

export default function ComplianceCalendarPage() {
  return (
    <PageShell
      title="Compliance Calendar"
      subtitle="Track upcoming compliance deadlines, reviews, and renewal windows across every governance module."
    >
      <Card title="Upcoming compliance events">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Date</th>
              <th className="font-medium pb-2">Event</th>
              <th className="font-medium pb-2">Category</th>
              <th className="font-medium pb-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {COMPLIANCE_CALENDAR.map(([date, event, category, status]) => (
              <tr key={event} className="border-t border-line align-top">
                <td className="py-2.5 text-ink whitespace-nowrap">{date}</td>
                <td className="py-2.5 font-semibold text-ink">
                  {event}
                  <div className="mt-0.5 text-[11px] font-normal text-muted">
                    System-generated; verify with a qualified professional before relying on this date.
                  </div>
                </td>
                <td className="py-2.5 text-xs text-muted">{category}</td>
                <td className="py-2.5"><Pill tone={STATUS_TONE[status]}>{status}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
