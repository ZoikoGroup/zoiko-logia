import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpenCheck,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileCheck2,
  FileClock,
  FileText,
  FolderKanban,
  GraduationCap,
  MessageSquareText,
  MoreHorizontal,
  Paperclip,
  Plus,
} from "lucide-react";

const workItems = [
  { title: "IFRS 15 revenue analysis", client: "Zoiko Sema Ltd.", type: "Workpaper", status: "Human review", tone: "bad", progress: 78, updated: "18 min ago", href: "/workpapers" },
  { title: "Lease classification assessment", client: "Zoiko Group Inc.", type: "Matter", status: "In progress", tone: "info", progress: 45, updated: "1 hr ago", href: "/workpapers" },
  { title: "Q2 compliance summary", client: "Internal reporting", type: "Draft report", status: "Draft", tone: "neutral", progress: 64, updated: "3 hr ago", href: "/drafts-reports" },
] as const;

const priorities = [
  { title: "Review Q2 workpaper", meta: "Meridian Health Group", due: "Due today", tone: "bad", icon: FileCheck2, href: "/review-tasks" },
  { title: "Approve evidence pack", meta: "Atlas Financial Partners", due: "Due tomorrow", tone: "warn", icon: Paperclip, href: "/evidence-packs" },
  { title: "Complete revenue pathway", meta: "CPD learning · 38% remaining", due: "Due 19 Jul", tone: "info", icon: GraduationCap, href: "/learning-practice" },
] as const;

const activity = [
  { icon: MessageSquareText, label: "Saved answer", title: "VAT treatment for mixed supply", when: "12 min ago", color: "text-brand" },
  { icon: CheckCircle2, label: "Review completed", title: "Atlas Financial Partners workpaper", when: "1 hr ago", color: "text-ok" },
  { icon: FileText, label: "Draft created", title: "Q2 compliance summary", when: "3 hr ago", color: "text-info" },
  { icon: Paperclip, label: "Evidence attached", title: "Lease classification assessment", when: "Yesterday", color: "text-warn" },
] as const;

function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)] ${className}`}>{children}</section>;
}

function PanelHeader({ title, subtitle, href, link = "View all" }: { title: string; subtitle?: string; href?: string; link?: string }) {
  return <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4"><div><h2 className="font-bold text-ink">{title}</h2>{subtitle && <p className="mt-1 text-[11px] text-muted">{subtitle}</p>}</div>{href && <Link href={href} className="flex items-center gap-1 text-xs font-semibold text-brand">{link}<ArrowUpRight size={13} /></Link>}</div>;
}

export default function MyWorkspacePage() {
  return (
    <main className="flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mx-auto max-w-[1480px]">
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            [BriefcaseBusiness, "7", "Active items", "3 updated today", "text-brand bg-brand/10", "/workpapers"],
            [CircleAlert, "3", "Priorities", "1 due today", "text-bad bg-bad/10", "/review-tasks"],
            [FileClock, "2", "Drafts", "Last edited 3h ago", "text-info bg-info/10", "/drafts-reports"],
            [GraduationCap, "6.5h", "CPD this month", "68% of monthly goal", "text-ok bg-ok/10", "/learning-practice"],
          ].map(([Icon, value, label, detail, color, href]) => <Link href={href as string} key={label as string} className="group rounded-2xl border border-line bg-panel p-4 hover:border-brand/40"><div className="flex items-start justify-between"><span className={`grid h-9 w-9 place-items-center rounded-xl ${color as string}`}><Icon size={18} /></span><ArrowUpRight size={14} className="text-muted group-hover:text-brand" /></div><strong className="mt-3 block text-2xl text-ink">{value as string}</strong><span className="block text-xs font-semibold text-ink">{label as string}</span><span className="mt-1 block text-[11px] text-muted">{detail as string}</span></Link>)}
        </div>

        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            [MessageSquareText, "Ask Kriton", "Start a source-grounded enquiry", "/ask-kriton", "text-ok"],
            [Plus, "New workpaper", "Create a governed analysis", "/workpapers", "text-info"],
            [Paperclip, "Add evidence", "Upload and map supporting files", "/evidence-packs", "text-warn"],
            [BookOpenCheck, "Saved answers", "Reuse trusted research", "/saved-answers", "text-brand"],
          ].map(([Icon, title, copy, href, color]) => <Link key={title as string} href={href as string} className="group flex items-center gap-3 rounded-2xl border border-line bg-panel p-4 hover:border-brand/40 hover:shadow-md"><span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-soft ${color as string}`}><Icon size={20} /></span><span className="min-w-0 flex-1"><strong className="block text-sm text-ink">{title as string}</strong><span className="block truncate text-[11px] text-muted">{copy as string}</span></span><ChevronRight size={16} className="text-muted transition group-hover:translate-x-1 group-hover:text-brand" /></Link>)}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(330px,.7fr)]">
          <Panel className="overflow-hidden">
            <PanelHeader title="Continue your work" subtitle="Recently active matters, workpapers, and reports" href="/workpapers" />
            <div className="p-3 sm:p-4">{workItems.map((item) => <Link key={item.title} href={item.href} className="group grid gap-3 border-b border-line px-1 py-4 last:border-0 md:grid-cols-[minmax(0,1fr)_120px_170px_24px] md:items-center"><div className="flex min-w-0 items-center gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand"><FolderKanban size={19} /></span><span className="min-w-0"><strong className="block truncate text-sm text-ink">{item.title}</strong><span className="block truncate text-xs text-muted">{item.client} · {item.type}</span><span className="mt-1 block text-[10px] text-muted">Updated {item.updated}</span></span></div><span className={`w-fit rounded-full px-2.5 py-1 text-[11px] font-semibold ${item.tone === "bad" ? "bg-bad/10 text-bad" : item.tone === "info" ? "bg-info/10 text-info" : "bg-chip text-muted"}`}>{item.status}</span><div className="flex items-center gap-2"><span className="h-2 flex-1 overflow-hidden rounded-full bg-soft"><span className="block h-full rounded-full bg-ok" style={{ width: `${item.progress}%` }} /></span><strong className="w-8 text-right text-[11px] text-muted">{item.progress}%</strong></div><ChevronRight size={16} className="text-muted group-hover:text-brand" /></Link>)}</div>
          </Panel>

          <Panel className="overflow-hidden">
            <PanelHeader title="Priority queue" subtitle="Ordered by deadline and risk" href="/review-tasks" />
            <div className="p-4">{priorities.map((item) => <Link href={item.href} key={item.title} className="flex gap-3 border-b border-line py-3 first:pt-0 last:border-0 last:pb-0"><span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${item.tone === "bad" ? "bg-bad/10 text-bad" : item.tone === "warn" ? "bg-warn/10 text-warn" : "bg-info/10 text-info"}`}><item.icon size={17} /></span><span className="min-w-0 flex-1"><strong className="block truncate text-xs text-ink">{item.title}</strong><span className="mt-1 block truncate text-[11px] text-muted">{item.meta}</span></span><span className={`h-fit whitespace-nowrap rounded-md px-2 py-1 text-[10px] font-semibold ${item.tone === "bad" ? "bg-bad/10 text-bad" : item.tone === "warn" ? "bg-warn/10 text-warn" : "bg-info/10 text-info"}`}>{item.due}</span></Link>)}</div>
            <div className="border-t border-line bg-soft/60 px-4 py-3"><Link href="/compliance-calendar" className="flex items-center justify-between text-xs font-semibold text-brand"><span className="flex items-center gap-2"><CalendarClock size={14} />Open my calendar</span><ArrowRight size={14} /></Link></div>
          </Panel>
        </div>

        <div className="mt-4">
          <Panel className="overflow-hidden">
            <PanelHeader title="Recent activity" subtitle="Governed timeline across all modules" href="/audit-logs" link="Audit trail" />
            <div className="p-5">{activity.map((item, index) => <div key={item.title} className="relative flex gap-3 pb-5 last:pb-0">{index < activity.length - 1 && <span className="absolute bottom-0 left-[17px] top-9 w-px bg-line" />}<span className={`z-10 grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line bg-panel ${item.color}`}><item.icon size={16} /></span><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><span><strong className="block text-xs text-ink">{item.label}</strong><span className="mt-1 block text-xs text-muted">{item.title}</span></span><span className="flex shrink-0 items-center gap-1 text-[10px] text-muted"><Clock3 size={10} />{item.when}</span></div></div><button aria-label={`More options for ${item.title}`} className="h-7 w-7 shrink-0 rounded-lg text-muted hover:bg-soft"><MoreHorizontal size={15} className="mx-auto" /></button></div>)}</div>
          </Panel>
        </div>

      </div>
    </main>
  );
}
