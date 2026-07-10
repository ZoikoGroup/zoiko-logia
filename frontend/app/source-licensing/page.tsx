"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { License } from "@/components/governance/License";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { StatTile } from "@/components/governance/StatTile";
import {
  ApiError,
  approveSourceVersion,
  createSource,
  getAuthToken,
  listSources,
  Source,
} from "@/lib/api";
import { Database, CheckCircle2, Clock, XCircle, FilePlus2, ListChecks, History, Upload } from "lucide-react";

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = {
  ACTIVE: "ok",
  APPROVED: "ok",
  PROPOSED: "warn",
  UNDER_REVIEW: "warn",
  DISPUTED: "bad",
  SUPERSEDED: "neutral",
  BLOCKED: "bad",
};

const CATEGORIES = ["standards", "tax", "audit", "payroll-compliance", "internal-policies", "education-content"];
const JURISDICTIONS = ["Global", "UK", "US", "IFRS", "EU", "UAE", "India"];

const LIST_ITEM =
  "rounded-xl border border-line/50 bg-soft/20 hover:bg-panel hover:shadow-md hover:border-line transition-all duration-200";

export default function SourceLicensingPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [category, setCategory] = useState(CATEGORIES[0]);
  const [title, setTitle] = useState("");
  const [sourceClass, setSourceClass] = useState("");
  const [jurisdiction, setJurisdiction] = useState(JURISDICTIONS[0]);
  const [file, setFile] = useState<File | null>(null);

  function loadSources() {
    listSources(getAuthToken())
      .then(setSources)
      .catch(() => setError("Could not load the source register from the server."));
  }

  useEffect(loadSources, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setSubmitting(true);
    try {
      await createSource(getAuthToken(), {
        category,
        title,
        source_class: sourceClass,
        jurisdiction_scope: jurisdiction,
        file,
      });
      setTitle("");
      setSourceClass("");
      setJurisdiction(JURISDICTIONS[0]);
      setFile(null);
      loadSources();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not submit source.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleApprove(source: Source) {
    setActionError("");
    try {
      await approveSourceVersion(getAuthToken(), source.id, source.latest_version.id);
      loadSources();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not approve source.");
    }
  }

  const approvedCount = sources.filter((s) => ["ACTIVE", "APPROVED"].includes(s.latest_version.status)).length;
  const pendingCount = sources.filter((s) => ["PROPOSED", "UNDER_REVIEW"].includes(s.latest_version.status)).length;
  const disputedCount = sources.filter((s) => ["DISPUTED", "BLOCKED"].includes(s.latest_version.status)).length;
  const recentlyApproved = sources
    .filter((s) => ["ACTIVE", "APPROVED"].includes(s.latest_version.status))
    .slice()
    .sort((a, b) => b.latest_version.created_at.localeCompare(a.latest_version.created_at))
    .slice(0, 5);

  return (
    <PageShell
      title="Source Licensing"
      subtitle="Approve, hold, expire, or restrict authoritative sources before they enter RAG/source bundles."
      showMetrics={false}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <StatTile label="Sources in register" value={sources.length} tone="brand" icon={Database} />
        <StatTile label="Approved / active" value={approvedCount} tone="ok" icon={CheckCircle2} />
        <StatTile label="Awaiting review" value={pendingCount} tone="warn" icon={Clock} />
        <StatTile label="Disputed / blocked" value={disputedCount} tone="bad" icon={XCircle} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_.9fr] gap-6 min-w-0 items-start">
        <div className="min-w-0 space-y-4">
          <div className={PANEL_CLASS}>
            <PanelHeader icon={FilePlus2} tone="warn" title="Submit source" />
            <form onSubmit={handleSubmit} className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
              <div>
                <label className="block text-xs font-medium text-muted mb-1.5">Category</label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted mb-1.5">Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  placeholder="e.g. FRS 102"
                  className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted mb-1.5">Source class</label>
                <input
                  value={sourceClass}
                  onChange={(e) => setSourceClass(e.target.value)}
                  required
                  placeholder="e.g. Professional standard-setter"
                  className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted mb-1.5">Jurisdiction</label>
                <input
                  list="jurisdiction-options"
                  value={jurisdiction}
                  onChange={(e) => setJurisdiction(e.target.value)}
                  placeholder="e.g. UK"
                  className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                />
                <datalist id="jurisdiction-options">
                  {JURISDICTIONS.map((j) => (
                    <option key={j} value={j} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted mb-1.5">Document</label>
                <label className="flex items-center gap-2 w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-muted outline-none focus-within:border-brand cursor-pointer hover:bg-panel">
                  <Upload size={14} className="shrink-0" />
                  <span className="truncate">{file ? file.name : "Attach file (optional)"}</span>
                  <input
                    type="file"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="hidden"
                  />
                </label>
              </div>
              <div>
                {formError && <p className="text-xs text-bad mb-2">{formError}</p>}
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60 transition-all duration-200"
                >
                  {submitting ? "Submitting..." : "Submit"}
                </button>
              </div>
            </form>
          </div>

          <div className={PANEL_CLASS}>
            <PanelHeader icon={ListChecks} title="Source approval register" subtitle={`${sources.length} sources on file`} />
            {error && <p className="text-xs text-bad mb-3">{error}</p>}
            {actionError && <p className="text-xs text-bad mb-3">{actionError}</p>}
            <div className="space-y-2 max-h-[560px] overflow-y-auto pr-1">
              {sources.map((source) => (
                <div key={source.id} className={`flex items-start justify-between gap-3 px-4 py-3 ${LIST_ITEM}`}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 text-sm font-semibold text-ink truncate" title={source.title}>
                        {source.title}
                      </span>
                      <Pill tone={STATUS_TONE[source.latest_version.status] ?? "neutral"}>
                        {source.latest_version.status}
                      </Pill>
                    </div>
                    {source.latest_version.note && (
                      <p className="mt-0.5 text-xs text-muted truncate" title={source.latest_version.note}>
                        {source.latest_version.note}
                      </p>
                    )}
                  </div>
                  {["PROPOSED", "UNDER_REVIEW"].includes(source.latest_version.status) && (
                    <button
                      onClick={() => handleApprove(source)}
                      className="shrink-0 text-xs font-semibold text-brand hover:underline whitespace-nowrap"
                    >
                      Approve
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <License />
          <div className={PANEL_CLASS}>
            <PanelHeader icon={History} tone="ok" title="Recently approved" />
            {recentlyApproved.length === 0 ? (
              <p className="text-sm text-muted">Nothing approved yet.</p>
            ) : (
              <div className="space-y-2">
                {recentlyApproved.map((source) => (
                  <div key={source.id} className={`px-3 py-2.5 ${LIST_ITEM}`}>
                    <div className="text-sm font-medium text-ink truncate" title={source.title}>
                      {source.title}
                    </div>
                    <div className="text-[11px] text-muted mt-0.5">
                      {source.jurisdiction_scope} · {new Date(source.latest_version.created_at).toLocaleDateString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  );
}
