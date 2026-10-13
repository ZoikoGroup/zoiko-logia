"use client";

import Link from "next/link";
import { BookmarkCheck, Briefcase, Clock3, FileText, MessageSquareText, ShieldCheck, Siren } from "lucide-react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { timeAgo, useCommandCenter } from "@/hooks/useCommandCenter";

/** The signed-in user's own activity, decisions, engagements and access —
 * all from GET /command-center. No sample tasks or activity. */
export default function MyWorkspacePage() {
  const { model, error } = useCommandCenter();

  return (
    <main className="flex-1 overflow-y-auto p-4">
      <PageHeader title="My Workspace" subtitle="Your activity, decisions waiting for you, and your access in one place." />

      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</p>
      )}
      {!model && !error && <p className="text-sm text-muted">Loading your workspace…</p>}

      {model && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Card title="Profile">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted">Name</dt><dd className="text-ink">{model.user.fullName || "—"}</dd>
              <dt className="text-muted">Email</dt><dd className="text-ink break-all">{model.user.email}</dd>
              <dt className="text-muted">Role</dt><dd className="text-ink">{model.user.role}</dd>
              <dt className="text-muted">Workspace</dt><dd className="text-ink">{model.workspace.name}</dd>
            </dl>
            <Link href="/account/security" className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-brand hover:underline">
              <ShieldCheck size={13} /> Account security
            </Link>
          </Card>

          <Card title="Your activity">
            <div className="grid grid-cols-3 gap-3 text-center">
              {[
                { label: "Questions (7 days)", value: model.counts.questionsLast7Days, href: "/ask-kriton" },
                { label: "Saved answers", value: model.counts.savedAnswers, href: "/saved-answers" },
                { label: "Drafts", value: model.counts.drafts, href: "/drafts-reports" },
              ].map((stat) => (
                <Link key={stat.label} href={stat.href} className="rounded-xl border border-line p-3 hover:bg-soft">
                  <span className="block text-2xl font-semibold text-ink">{stat.value}</span>
                  <span className="block text-[11px] text-muted">{stat.label}</span>
                </Link>
              ))}
            </div>
          </Card>

          <Card title="Recent activity">
            {model.recentWork.length === 0 ? (
              <p className="text-sm text-muted">No activity yet. Ask Kriton a question to get started.</p>
            ) : (
              <ul className="space-y-3">
                {model.recentWork.map((item) => {
                  const Icon = item.kind === "Saved answer" ? BookmarkCheck : item.kind.startsWith("Draft") ? FileText : MessageSquareText;
                  return (
                    <li key={item.id}>
                      <Link href={item.href} className="flex items-start gap-2.5 hover:text-brand">
                        <Icon size={15} className="mt-0.5 shrink-0 text-brand" />
                        <span>
                          <span className="block text-sm text-ink">{item.title}</span>
                          <span className="flex items-center gap-1 text-[11px] text-muted">
                            <Clock3 size={11} /> {item.kind} · {timeAgo(item.at)}
                          </span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <Card title="Waiting for your decision">
            {model.reviewQueue.length === 0 ? (
              <p className="text-sm text-muted">Nothing is waiting for you.</p>
            ) : (
              <ul className="space-y-3">
                {model.reviewQueue.map((task) => (
                  <li key={task.id} className="flex items-start justify-between gap-2">
                    <Link href={task.drilldownTarget} className="text-sm text-ink hover:text-brand">
                      <span className="block text-[11px] font-bold uppercase tracking-wide text-muted">{task.type}</span>
                      {task.title}
                    </Link>
                    <Pill tone={task.blockedReason ? "neutral" : "warn"}>
                      {task.blockedReason ? "Needs 2nd approver" : timeAgo(task.submittedAt) || "Pending"}
                    </Pill>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Your engagements">
            {model.activeMatters.length === 0 ? (
              <p className="text-sm text-muted">You are not a member of any engagement yet.</p>
            ) : (
              <ul className="space-y-2">
                {model.activeMatters.map((matter) => (
                  <li key={matter.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="flex items-center gap-2 text-ink"><Briefcase size={14} className="text-brand" />{matter.name}</span>
                    <span className="text-xs text-muted">{matter.myRole}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {model.breakGlass.length > 0 && (
            <Card title="Your emergency access">
              <ul className="space-y-2">
                {model.breakGlass.map((grant) => (
                  <li key={grant.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="flex items-center gap-2 text-ink">
                      <Siren size={14} className="text-warn" />
                      {grant.permissions.join(", ")}
                    </span>
                    <Pill tone={grant.status === "active" ? "warn" : "neutral"}>
                      {grant.status === "active" && grant.expiresAt
                        ? `Active until ${new Date(grant.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                        : grant.status}
                    </Pill>
                  </li>
                ))}
              </ul>
              <Link href="/break-glass" className="mt-3 inline-block text-xs font-semibold text-brand hover:underline">Manage</Link>
            </Card>
          )}
        </div>
      )}
    </main>
  );
}
