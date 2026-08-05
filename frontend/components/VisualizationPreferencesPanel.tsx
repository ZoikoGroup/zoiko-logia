"use client";

import { useEffect, useState } from "react";
import { getVisualizationPreferences, putVisualizationPreferences, resetVisualizationPreferences, type VisualizationPreferences } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

const defaults: VisualizationPreferences = { preferred_output: "auto", comparison_preference: "auto", trend_preference: "auto", composition_preference: "auto", value_display: "auto", label_orientation: "auto", visual_density: "standard", contrast_preference: "system", reduced_motion: false, table_alternative_default_open: false, schema_version: "1.0" };

const choices = {
  preferred_output: ["auto", "chart", "table"], comparison_preference: ["auto", "grouped_bar", "dumbbell", "lollipop", "diverging_bar"],
  trend_preference: ["auto", "line", "area"], composition_preference: ["auto", "donut", "composition_bar", "stacked_bar", "percentage_stacked_bar"],
  value_display: ["auto", "absolute", "percentage"], label_orientation: ["auto", "horizontal", "vertical"],
  visual_density: ["compact", "standard", "detailed"], contrast_preference: ["system", "standard", "high"],
} as const;

export function VisualizationPreferencesPanel() {
  const { session } = useAuth();
  const [value, setValue] = useState(defaults);
  const [status, setStatus] = useState("");
  useEffect(() => { if (session?.access_token) getVisualizationPreferences(session.access_token).then(setValue).catch(() => setStatus("Could not load preferences.")); }, [session?.access_token]);
  const update = (key: keyof VisualizationPreferences, next: string | boolean) => setValue((current) => ({ ...current, [key]: next }));
  return <section className="rounded-2xl border border-line bg-panel p-5" aria-labelledby="visualization-preferences-title">
    <h2 id="visualization-preferences-title" className="text-lg font-bold text-ink">Visualization Preferences</h2>
    <p className="mt-1 max-w-2xl text-sm text-muted">These preferences affect presentation only. They do not alter calculations and apply only when compatible with the data.</p>
    <div className="mt-5 grid gap-4 md:grid-cols-2">
      {Object.entries(choices).map(([key, options]) => <label key={key} className="text-sm font-semibold text-ink">
        {key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase())}
        <select className="mt-1 block w-full rounded-lg border border-line bg-panel px-3 py-2 font-normal" value={String(value[key as keyof VisualizationPreferences])} onChange={(event) => update(key as keyof VisualizationPreferences, event.target.value)}>
          {options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}
        </select>
      </label>)}
      {(["reduced_motion", "table_alternative_default_open"] as const).map((key) => <label key={key} className="flex items-center gap-2 text-sm font-semibold text-ink">
        <input type="checkbox" checked={value[key]} onChange={(event) => update(key, event.target.checked)} /> {key.replaceAll("_", " ")}
      </label>)}
    </div>
    <div className={`mt-5 rounded-xl border border-line p-4 ${value.contrast_preference === "high" ? "border-ink bg-bg" : "bg-soft"}`} aria-label="Visualization preference preview">
      <p className="text-xs font-bold uppercase tracking-wider">Local preview</p>
      <div className="mt-3 flex h-20 items-end gap-3" aria-label="Fixed sample values: Alpha 40, Beta 70, Gamma 55">
        {[40, 70, 55].map((height, index) => <div key={height} className="flex flex-1 flex-col items-center gap-1"><div className="w-full bg-brand" style={{ height }} /><span className="text-xs">{["Alpha", "Beta", "Gamma"][index]}</span></div>)}
      </div>
    </div>
    <div className="mt-5 flex gap-3">
      <button type="button" className="rounded-lg bg-brand px-4 py-2 text-sm font-bold text-white" onClick={async () => { if (!session?.access_token) return; setValue(await putVisualizationPreferences(session.access_token, value)); setStatus("Preferences saved."); }}>Save preferences</button>
      <button type="button" className="rounded-lg border border-line px-4 py-2 text-sm font-bold" onClick={async () => { if (!session?.access_token) return; setValue(await resetVisualizationPreferences(session.access_token)); setStatus("Defaults restored."); }}>Reset to defaults</button>
    </div>
    <p aria-live="polite" className="mt-3 text-sm text-muted">{status}</p>
  </section>;
}
