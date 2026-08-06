"use client";
import { useEffect, useState } from "react";
import { ShieldCheck, RotateCcw, Trash2 } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import {
  getAuthToken, getPersonalizationConsent, putPersonalizationConsent, getPersonalizationSummary,
  resetPersonalizationProfile, deletePersonalizationProfile, defaultPersonalizationConsent,
  type PersonalizationConsent, type PersonalizationSummary,
} from "@/lib/api";

const historyWindows: { value: PersonalizationConsent["personalization_history_window"]; label: string }[] = [
  { value: "30_days", label: "Last 30 days" },
  { value: "90_days", label: "Last 90 days" },
  { value: "180_days", label: "Last 180 days" },
];

function summarySentence(summary: PersonalizationSummary): string {
  const family = Object.entries(summary.top_family_preferences)[0];
  const intent = Object.entries(summary.top_intent_preferences)[0];
  const parts: string[] = [];
  if (intent) parts.push(`you usually choose ${intent[1].replaceAll("_", " ")} charts for ${intent[0].replaceAll("_", " ")}`);
  if (family) parts.push(`${family[1].replaceAll("_", " ")} charts for ${family[0].replaceAll("_", " ")} views`);
  const detail = parts.length ? parts.join(" and ") : "no clear pattern has emerged yet";
  return `Across ${summary.interaction_count} eligible interactions, ${detail}.`;
}

export default function VisualizationPersonalizationPage() {
  const [consent, setConsent] = useState<PersonalizationConsent>(defaultPersonalizationConsent);
  const [summary, setSummary] = useState<PersonalizationSummary | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      setError("");
      const token = getAuthToken();
      const [loadedConsent, loadedSummary] = await Promise.all([
        getPersonalizationConsent(token), getPersonalizationSummary(token),
      ]);
      setConsent(loadedConsent);
      setSummary(loadedSummary);
    } catch {
      setError("Could not load personalization settings.");
    }
  }
  useEffect(() => { load(); }, []);

  async function save(next: PersonalizationConsent) {
    setSaving(true); setStatus("");
    try {
      const saved = await putPersonalizationConsent(getAuthToken(), next);
      setConsent(saved);
      setStatus("Settings saved.");
    } catch {
      setError("Could not save personalization settings.");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setStatus("");
    try { await resetPersonalizationProfile(getAuthToken()); setStatus("Learned recommendations reset."); await load(); }
    catch { setError("Could not reset learned recommendations."); }
  }

  async function handleDelete() {
    setStatus("");
    try {
      await deletePersonalizationProfile(getAuthToken());
      setStatus("Personalization disabled and profile deleted.");
      await load();
    } catch { setError("Could not delete your personalization profile."); }
  }

  return (
    <PageShell title="Visualization Personalization" subtitle="Optional, consent-based recommendations based on your own repeated chart choices." showMetrics={false}>
      <section className="rounded-2xl border border-line bg-panel p-4">
        <div className="flex items-center gap-2"><ShieldCheck size={16} className="text-brand" aria-hidden="true" /><h1 className="font-bold">Visualization Personalization</h1></div>
        <p className="mt-2 text-xs text-muted">
          When enabled, Ask Kriton may occasionally break a near-tie between equally valid chart choices in favor of
          the type you tend to pick for similar questions. It only ever affects which chart is shown — never your
          answer text, calculations, or data. Your query text and financial values are never used or stored for this.
          You can change scope, reset what&rsquo;s been learned, or turn this off at any time; nothing is inferred
          just from continuing to use Ask Kriton.
        </p>
        {error && <p className="mt-3 text-sm text-bad" role="alert">{error}</p>}
        {status && <p className="mt-3 text-sm text-ok" role="status" aria-live="polite">{status}</p>}

        <div className="mt-4 flex items-center gap-2">
          <input
            id="personalization-enabled" type="checkbox" checked={consent.personalization_enabled}
            onChange={(e) => save({ ...consent, personalization_enabled: e.target.checked })}
            disabled={saving} className="h-4 w-4"
          />
          <label htmlFor="personalization-enabled" className="text-sm font-semibold">Enable personalized recommendations</label>
        </div>

        <fieldset className="mt-4" disabled={!consent.personalization_enabled || saving}>
          <legend className="text-xs font-bold uppercase tracking-[0.1em] text-muted">History window</legend>
          <div className="mt-2 flex flex-wrap gap-3">
            {historyWindows.map((window) => (
              <label key={window.value} className="flex items-center gap-1.5 text-xs">
                <input
                  type="radio" name="history-window" value={window.value}
                  checked={consent.personalization_history_window === window.value}
                  onChange={() => save({ ...consent, personalization_history_window: window.value })}
                />
                {window.label}
              </label>
            ))}
          </div>

          <legend className="mt-4 text-xs font-bold uppercase tracking-[0.1em] text-muted">Learning sources</legend>
          <div className="mt-2 flex flex-col gap-2 text-xs">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox" checked={consent.allow_view_switch_learning}
                onChange={(e) => save({ ...consent, allow_view_switch_learning: e.target.checked })}
              />
              Learn from switching to &ldquo;Try another view&rdquo;
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox" checked={consent.allow_export_learning}
                onChange={(e) => save({ ...consent, allow_export_learning: e.target.checked })}
              />
              Learn from PNG/CSV exports
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox" checked={consent.allow_save_learning}
                onChange={(e) => save({ ...consent, allow_save_learning: e.target.checked })}
              />
              Learn from saved visualizations
            </label>
          </div>
        </fieldset>
      </section>

      <section className="mt-5 rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-bold">Current learned summary</h2>
        {!consent.personalization_enabled && <p className="mt-2 text-sm text-muted">Personalization is off — enable it above to start collecting evidence.</p>}
        {consent.personalization_enabled && summary && !summary.eligible && (
          <p className="mt-2 text-sm text-muted">Collecting evidence — {summary.interaction_count} interaction(s) across {summary.conversation_count} conversation(s) so far.</p>
        )}
        {consent.personalization_enabled && summary && summary.eligible && (
          <p className="mt-2 text-sm text-ink">{summarySentence(summary)}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={handleReset} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-xs font-bold">
            <RotateCcw size={13} aria-hidden="true" />Reset learned recommendations
          </button>
          <button type="button" onClick={handleDelete} className="inline-flex items-center gap-1.5 rounded-lg border border-bad/40 px-3 py-2 text-xs font-bold text-bad">
            <Trash2 size={13} aria-hidden="true" />Disable and delete profile
          </button>
        </div>
      </section>
    </PageShell>
  );
}
