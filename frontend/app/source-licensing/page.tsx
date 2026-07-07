"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { License } from "@/components/governance/License";
import { Pill } from "@/components/governance/Pill";
import {
  ApiError,
  approveSourceVersion,
  createSource,
  getAuthToken,
  listSources,
  Source,
} from "@/lib/api";

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

export default function SourceLicensingPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [category, setCategory] = useState(CATEGORIES[0]);
  const [title, setTitle] = useState("");
  const [sourceClass, setSourceClass] = useState("");

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
      await createSource(getAuthToken(), { category, title, source_class: sourceClass });
      setTitle("");
      setSourceClass("");
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

  return (
    <PageShell
      title="Source Licensing"
      subtitle="Approve, hold, expire, or restrict authoritative sources before they enter RAG/source bundles."
    >
      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_.9fr] gap-6">
        <div className="space-y-4">
          <Card title="Submit source">
            <form onSubmit={handleSubmit} className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
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
                {formError && <p className="text-xs text-bad mb-2">{formError}</p>}
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
                >
                  {submitting ? "Submitting..." : "Submit"}
                </button>
              </div>
            </form>
          </Card>

          <Card title="Source approval register">
            {error && <p className="text-xs text-bad mb-3">{error}</p>}
            {actionError && <p className="text-xs text-bad mb-3">{actionError}</p>}
            <table className="w-full text-sm">
              <tbody>
                {sources.map((source) => (
                  <tr key={source.id} className="border-t border-line first:border-t-0 align-top">
                    <td className="py-2.5 font-semibold text-ink">{source.title}</td>
                    <td className="py-2.5">
                      <Pill tone={STATUS_TONE[source.latest_version.status] ?? "neutral"}>
                        {source.latest_version.status}
                      </Pill>
                    </td>
                    <td className="py-2.5 text-xs text-muted">{source.latest_version.note}</td>
                    <td className="py-2.5 text-right">
                      {["PROPOSED", "UNDER_REVIEW"].includes(source.latest_version.status) && (
                        <button
                          onClick={() => handleApprove(source)}
                          className="text-xs text-brand hover:underline whitespace-nowrap"
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
        <License />
      </div>
    </PageShell>
  );
}
