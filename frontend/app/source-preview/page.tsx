"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, ExternalLink, FileText, History, ShieldCheck } from "lucide-react";
import { getAuthToken, openSourceUrl } from "@/lib/api";

type EvidencePayload = {
  title: string;
  sourceId: string;
  sourceUrl: string | null;
  excerpt: string;
  query: string;
  correlationId?: string;
  savedAt: number;
};

export default function SourcePreviewPage() {
  const [evidence, setEvidence] = useState<EvidencePayload | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const key = new URLSearchParams(window.location.search).get("key");
    if (!key) return setMissing(true);
    try {
      const stored = window.localStorage.getItem(key);
      if (!stored) return setMissing(true);
      setEvidence(JSON.parse(stored));
    } catch {
      setMissing(true);
    }
  }, []);

  return (
    <main className="min-h-screen bg-soft px-4 py-5 text-ink sm:px-6">
      <div className="mx-auto max-w-2xl">
        <Link href="/ask-kriton" className="inline-flex items-center gap-2 text-sm font-semibold text-muted hover:text-brand">
          <ArrowLeft size={16} /> Back to Kriton
        </Link>

        {missing ? (
          <div className="mt-8 rounded-2xl border border-line bg-panel p-6">
            <h1 className="text-xl font-bold">Evidence preview unavailable</h1>
            <p className="mt-2 text-sm leading-6 text-muted">Open the source again from the Kriton answer that used it.</p>
          </div>
        ) : evidence ? (
          <article className="mt-4 overflow-hidden rounded-xl border border-line bg-panel shadow-sm">
            <header className="border-b border-line bg-soft/60 p-4">
              <div className="flex items-start gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand/5 text-brand">
                  {evidence.sourceId === "src-kriton-user-provided-data" ? <BookOpen size={19} /> : <FileText size={19} />}
                </span>
                <div>
                  <div className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-ok"><ShieldCheck size={13} /> Evidence used</div>
                  <h1 className="mt-1 text-base font-bold leading-6">{evidence.title}</h1>
                  <p className="mt-1 text-xs text-muted">This is the supporting passage Kriton used for this answer.</p>
                </div>
              </div>
            </header>

            <div className="space-y-4 p-4">
              <section>
                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">Question supported</h2>
                <p className="mt-2 rounded-xl bg-soft px-4 py-3 text-sm leading-6">{evidence.query}</p>
              </section>
              <section>
                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">Relevant evidence</h2>
                <p className="mt-2 whitespace-pre-wrap rounded-xl border border-line bg-bg px-4 py-4 text-sm leading-7">{evidence.excerpt}</p>
              </section>
              <div className="flex flex-wrap gap-3 border-t border-line pt-4">
                {evidence.sourceUrl && (
                  <button type="button" onClick={() => openSourceUrl(getAuthToken(), evidence.sourceUrl!)} className="inline-flex items-center gap-2 rounded-lg bg-brand px-3 py-2 text-xs font-semibold text-white hover:bg-brand-2">
                    Open original source <ExternalLink size={13} />
                  </button>
                )}
                {evidence.correlationId && (
                  <Link href={`/audit-replay?correlation_id=${encodeURIComponent(evidence.correlationId)}`} className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs font-semibold hover:border-brand/30 hover:text-brand">
                    View audit trail <History size={13} />
                  </Link>
                )}
              </div>
            </div>
          </article>
        ) : null}
      </div>
    </main>
  );
}
