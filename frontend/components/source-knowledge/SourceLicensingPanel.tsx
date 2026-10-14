"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { License } from "@/components/governance/License";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import {
  ApiError,
  approveSourceVersion,
  createSource,
  getAuthToken,
  listSources,
  Source,
} from "@/lib/api";
import { FilePlus2, ListChecks, Upload } from "lucide-react";

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

export function SourceLicensingPanel() {
  const { data, error, loading, signedOut, reload } = useLiveData(`source-licensing`, (token, signal) => listSources(token, undefined, signal), 20_000);
  const sources = data ?? [];
  const [actionError, setActionError] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [usageRights, setUsageRights] = useState<Record<string, boolean>>({});

  const [category, setCategory] = useState(CATEGORIES[0]);
  const [title, setTitle] = useState("");
  const [sourceClass, setSourceClass] = useState("");
  const [jurisdiction, setJurisdiction] = useState(JURISDICTIONS[0]);
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [termsReference, setTermsReference] = useState("");
  const [effectiveTo, setEffectiveTo] = useState("");
  const [file, setFile] = useState<File | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    if (file && !rightsConfirmed) {
      setFormError("Confirm permission to ingest, index, and retain the document before uploading.");
      return;
    }
    setSubmitting(true);
    try {
      await createSource(getAuthToken(), {
        category,
        title,
        source_class: sourceClass,
        jurisdiction_scope: jurisdiction,
        file,
        rights: { ...usageRights, ...(rightsConfirmed ? { ingestion: true, indexing: true, retention: true } : {}) },
        terms_reference: termsReference,
        effective_to: effectiveTo || undefined,
      });
      setTitle("");
      setSourceClass("");
      setJurisdiction(JURISDICTIONS[0]);
      setFile(null);
      setRightsConfirmed(false);
      setUsageRights({});
      setTermsReference("");
      setEffectiveTo("");
      reload();
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
      reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not approve source.");
    }
  }

  const pendingCount = sources.filter((s) => ["PROPOSED", "UNDER_REVIEW"].includes(s.latest_version.status)).length;
  // Only sources that need a decision; the full catalogue is Source Library.
  const needsAction = sources.filter((s) => ["PROPOSED", "UNDER_REVIEW", "DISPUTED", "BLOCKED"].includes(s.latest_version.status));

  return (
    <>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />

      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_.9fr] gap-6 min-w-0 items-start">
        <div className="min-w-0 space-y-4">
          <div className={PANEL_CLASS}>
            <PanelHeader icon={FilePlus2} tone="warn" title="Submit source" />
            <form onSubmit={handleSubmit} className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
              <div className="sm:col-span-3 space-y-2 text-xs text-muted">
                <label className="flex gap-2 items-center"><input type="checkbox" checked={rightsConfirmed} onChange={(e) => setRightsConfirmed(e.target.checked)} />I have permission to ingest, index, and retain this document.</label>
                <label className="block">Licence or terms reference<input aria-label="Licence or terms reference" value={termsReference} onChange={(e) => setTermsReference(e.target.value)} className="ml-2 rounded border border-line bg-soft px-2 py-1" /></label>
                <label className="block">Source effective until<input aria-label="Source effective until" type="date" value={effectiveTo} onChange={(e) => setEffectiveTo(e.target.value)} className="ml-2 rounded border border-line bg-soft px-2 py-1" /></label>
                <fieldset className="flex flex-wrap gap-3"><legend>Additional permitted uses (select only those covered by your terms)</legend>{["retrieval", "model_transmission", "display", "summary", "export"].map((operation) => <label key={operation} className="flex gap-1 items-center"><input type="checkbox" checked={usageRights[operation] ?? false} onChange={(e) => setUsageRights((rights) => ({ ...rights, [operation]: e.target.checked }))} />{operation.replaceAll("_", " ")}</label>)}</fieldset>
                <p>Unselected uses remain restricted.</p>
              </div>
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
            <PanelHeader icon={ListChecks} title="Source approval register" subtitle={data ? `${pendingCount} awaiting review · ${needsAction.length - pendingCount} disputed or blocked` : "Source register"} />
            {actionError && <p className="text-xs text-bad mb-3">{actionError}</p>}
            <div className="space-y-2 max-h-[560px] overflow-y-auto pr-1">
              {data && needsAction.length === 0 && (
                <p className="text-sm text-muted">Nothing awaiting a decision. Browse every source in <Link href="/source-library" className="text-brand hover:underline">Source Library</Link>.</p>
              )}
              {needsAction.map((source) => (
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
        </div>
      </div>
    </>
  );
}
