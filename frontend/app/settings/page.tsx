"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState, useSyncExternalStore } from "react";
import { Bell, KeyRound, Loader2, MessageSquare, Palette, UserRound } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { LoadError } from "@/components/governance/LiveStatus";
import { Tabs } from "@/components/shell/Tabs";
import { useTabParam } from "@/components/shell/useTabParam";
import { useTheme } from "@/components/shell/ThemeProvider";
import { useAuth } from "@/hooks/useAuth";
import { readCookie, subscribeCookies, writeCookie } from "@/lib/cookie-store";
import { REDUCE_MOTION_COOKIE, TEXT_SIZE_COOKIE, type TextSize } from "@/lib/theme";
import { ApiError, getAuthToken, getMySettings, updateMyProfile, updateMySettings, type MySettings } from "@/lib/api";

const TABS = [
  { label: "Profile", slug: "profile" },
  { label: "Notifications", slug: "notifications" },
  { label: "Appearance", slug: "appearance" },
  { label: "Kriton defaults", slug: "kriton" },
  { label: "Security", slug: "security" },
];
const TAB_SLUGS = TABS.map((t) => t.slug);
const YEAR = 60 * 60 * 24 * 365;

const BUTTON = "rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-2 disabled:opacity-60";
const INPUT = "w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand";

function Saved({ show }: { show: boolean }) {
  return show ? <span role="status" className="text-xs font-semibold text-ok">Saved</span> : null;
}

export default function SettingsPage() {
  return (
    <Suspense fallback={null}>
      <Settings />
    </Suspense>
  );
}

function Settings() {
  const [tab, setTab] = useTabParam("profile", TAB_SLUGS);
  const [settings, setSettings] = useState<MySettings | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    getMySettings(getAuthToken())
      .then(setSettings)
      .catch(() => setLoadError("Your saved settings could not be loaded. Check the backend is running and refresh."));
  }, []);

  return (
    <PageShell title="Settings" subtitle="Your profile, notifications, appearance and Kriton defaults.">
      <div className="max-w-3xl space-y-4">
        <Tabs tabs={TABS} activeSlug={tab} onChange={setTab} />
        {loadError && (tab === "notifications" || tab === "kriton") && <LoadError message={loadError} />}
        {tab === "profile" && <ProfileTab />}
        {tab === "notifications" && <NotificationsTab settings={settings} onSaved={setSettings} />}
        {tab === "appearance" && <AppearanceTab />}
        {tab === "kriton" && <KritonTab settings={settings} onSaved={setSettings} />}
        {tab === "security" && <SecurityTab />}
      </div>
    </PageShell>
  );
}

function ProfileTab() {
  const { profile } = useAuth();
  if (!profile) {
    return <div className={PANEL_CLASS}><div className="flex justify-center py-8 text-muted"><Loader2 size={16} className="animate-spin" /></div></div>;
  }
  // Keyed so the form starts from the loaded profile, not an empty one.
  return <ProfileForm key={profile.id} />;
}

function ProfileForm() {
  const { profile, refreshProfile } = useAuth();
  const [firstName, setFirstName] = useState(profile?.first_name ?? "");
  const [lastName, setLastName] = useState(profile?.last_name ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await updateMyProfile(getAuthToken(), { first_name: firstName.trim(), last_name: lastName.trim() });
      await refreshProfile();
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your name could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  if (!profile) return null;

  return (
    <form onSubmit={save} className={PANEL_CLASS}>
      <PanelHeader icon={UserRound} title="Profile" subtitle="How your name appears to your team" />
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1.5 text-xs font-medium text-muted">
          First name
          <input id="profile-first-name" value={firstName} onChange={(e) => { setFirstName(e.target.value); setSaved(false); }} required maxLength={80} className={INPUT} />
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted">
          Last name
          <input id="profile-last-name" value={lastName} onChange={(e) => { setLastName(e.target.value); setSaved(false); }} maxLength={80} className={INPUT} />
        </label>
        <div className="space-y-1.5 text-xs font-medium text-muted">
          Email
          <p className="rounded-lg border border-line bg-soft/40 px-3 py-2 text-sm text-ink">{profile.email}</p>
        </div>
        <div className="space-y-1.5 text-xs font-medium text-muted">
          Role
          <p className="rounded-lg border border-line bg-soft/40 px-3 py-2 text-sm text-ink">{profile.role}</p>
        </div>
      </div>
      <p className="mt-3 text-[11px] text-muted">Your email and role are managed by your organisation&apos;s Admin.</p>
      {error && <p className="mt-3 text-xs text-bad">{error}</p>}
      <div className="mt-4 flex items-center gap-3">
        <button type="submit" disabled={saving || !firstName.trim()} className={BUTTON}>{saving ? "Saving…" : "Save name"}</button>
        <Saved show={saved} />
      </div>
    </form>
  );
}

function NotificationsTab({ settings, onSaved }: { settings: MySettings | null; onSaved: (s: MySettings) => void }) {
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");

  async function toggle(kind: string, enabled: boolean) {
    if (!settings) return;
    const muted = new Set(settings.muted_notifications);
    if (enabled) muted.delete(kind); else muted.add(kind);
    setSaving(kind);
    setError("");
    try {
      onSaved(await updateMySettings(getAuthToken(), { muted_notifications: [...muted] }));
    } catch {
      setError("That change could not be saved.");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className={PANEL_CLASS}>
      <PanelHeader icon={Bell} title="Notifications" subtitle="Choose what appears under the bell. Items that need your action always show." />
      {!settings ? (
        <div className="flex justify-center py-8 text-muted"><Loader2 size={16} className="animate-spin" /></div>
      ) : (
        <ul className="divide-y divide-line">
          {settings.notification_kinds.map(({ kind, label }) => {
            const enabled = !settings.muted_notifications.includes(kind);
            return (
              <li key={kind} className="flex items-center justify-between gap-4 py-3">
                <label htmlFor={`notify-${kind}`} className="text-sm text-ink">{label}</label>
                <button
                  id={`notify-${kind}`}
                  type="button"
                  role="switch"
                  aria-checked={enabled}
                  disabled={saving === kind}
                  onClick={() => toggle(kind, !enabled)}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition ${enabled ? "bg-brand" : "bg-line"} disabled:opacity-60`}
                >
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${enabled ? "left-[22px]" : "left-0.5"}`} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {error && <p className="mt-3 text-xs text-bad">{error}</p>}
      <p className="mt-3 text-[11px] text-muted">Turning a type off stops new ones; ones you already have stay in your list. Email notifications are not available yet.</p>
    </div>
  );
}

function useCookie(name: string): string | null {
  return useSyncExternalStore(subscribeCookies, () => readCookie(name), () => null);
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme();
  const textSize = (useCookie(TEXT_SIZE_COOKIE) as TextSize | null) ?? "normal";
  const reduceMotion = useCookie(REDUCE_MOTION_COOKIE) === "true";

  function setTextSize(size: TextSize) {
    document.documentElement.setAttribute("data-text-size", size);
    writeCookie(TEXT_SIZE_COOKIE, size, YEAR);
  }

  function setReduceMotion(on: boolean) {
    document.documentElement.setAttribute("data-reduce-motion", String(on));
    writeCookie(REDUCE_MOTION_COOKIE, String(on), YEAR);
  }

  const choice = (active: boolean) =>
    `rounded-lg border px-4 py-2 text-sm font-semibold ${active ? "border-brand bg-brand/10 text-brand" : "border-line text-ink hover:bg-soft"}`;

  return (
    <div className={PANEL_CLASS}>
      <PanelHeader icon={Palette} title="Appearance" subtitle="Saved in this browser" />
      <div className="space-y-5">
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-muted">Theme</legend>
          <div className="flex flex-wrap gap-2">
            <button type="button" aria-pressed={theme === "light"} onClick={() => setTheme("light")} className={choice(theme === "light")}>Light</button>
            <button type="button" aria-pressed={theme === "dark"} onClick={() => setTheme("dark")} className={choice(theme === "dark")}>Dark</button>
          </div>
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-muted">Text size</legend>
          <div className="flex flex-wrap gap-2">
            <button type="button" aria-pressed={textSize === "normal"} onClick={() => setTextSize("normal")} className={choice(textSize === "normal")}>Normal</button>
            <button type="button" aria-pressed={textSize === "large"} onClick={() => setTextSize("large")} className={choice(textSize === "large")}>Large</button>
          </div>
        </fieldset>
        <label className="flex items-center justify-between gap-4">
          <span>
            <span className="block text-sm text-ink">Reduce motion</span>
            <span className="block text-[11px] text-muted">Turns off animations and transitions.</span>
          </span>
          <input id="reduce-motion" type="checkbox" checked={reduceMotion} onChange={(e) => setReduceMotion(e.target.checked)} className="h-4 w-4" />
        </label>
      </div>
    </div>
  );
}

function KritonTab({ settings, onSaved }: { settings: MySettings | null; onSaved: (s: MySettings) => void }) {
  const [jurisdiction, setJurisdiction] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const value = jurisdiction ?? settings?.default_jurisdiction ?? "";

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      onSaved(await updateMySettings(getAuthToken(), { default_jurisdiction: value }));
      setSaved(true);
    } catch {
      setError("Your default could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className={PANEL_CLASS}>
      <PanelHeader icon={MessageSquare} title="Kriton defaults" subtitle="Used when you start a new question in Ask Kriton" />
      {!settings ? (
        <div className="flex justify-center py-8 text-muted"><Loader2 size={16} className="animate-spin" /></div>
      ) : (
        <>
          <label className="block max-w-xs space-y-1.5 text-xs font-medium text-muted">
            Default jurisdiction
            <select id="default-jurisdiction" value={value} onChange={(e) => { setJurisdiction(e.target.value); setSaved(false); }} className={INPUT}>
              <option value="">No default (Kriton works it out)</option>
              {settings.jurisdictions.map((j) => <option key={j} value={j}>{j}</option>)}
            </select>
          </label>
          <p className="mt-3 text-[11px] text-muted">You can still change it for any single question.</p>
          {error && <p className="mt-3 text-xs text-bad">{error}</p>}
          <div className="mt-4 flex items-center gap-3">
            <button type="submit" disabled={saving} className={BUTTON}>{saving ? "Saving…" : "Save default"}</button>
            <Saved show={saved} />
          </div>
        </>
      )}
    </form>
  );
}

function SecurityTab() {
  return (
    <div className={PANEL_CLASS}>
      <PanelHeader icon={KeyRound} title="Security" subtitle="Two-step verification and signed-in sessions" />
      <p className="text-sm text-ink">Turn on two-step verification and sign out of other devices on the account security page.</p>
      <Link href="/account/security" className={`${BUTTON} mt-4 inline-block`}>Open account security</Link>
    </div>
  );
}
