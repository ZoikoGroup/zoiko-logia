"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity, BarChart3, CircleCheck, Coins, Cpu, Eye, FileText, Gavel, Layers, LayoutGrid, Link2, Lock, Server, Settings,
  ShieldCheck, TriangleAlert, UserCog, Users, Wallet, Zap,
} from "lucide-react";
import type { PlatformCommand } from "@/lib/api";
import {
  Assurance, CommercialAssurance, DecisionQueue, EvidenceAudit, KritonControlPlane, PrivilegedAccess, Reliability, TenantGovernance,
} from "@/components/platform/command";

/** The Super Admin sidebar, after the ZoikoLogia command-center design. Every
 * entry opens a platform page (never a tenant workspace page): the command
 * center, the Companies and Accounts directory, or a section page under
 * /super-admin/<slug> that shows the live platform data for its area. A
 * section whose own management tools are not built says so (`partial`). */

export type PlatformSection = {
  slug: string; label: string; icon: LucideIcon; summary: string;
  /** True when the page shows only the related live data, not the section's own tools yet. */
  partial?: boolean;
  render: (data: PlatformCommand) => ReactNode;
};
export type NavEntry = { label: string; icon: LucideIcon; href: string };

export const SECTIONS: PlatformSection[] = [
  { slug: "executive-decisions", label: "Executive Decisions", icon: Gavel,
    summary: "Every exception that needs an accountable decision, ranked by risk.",
    render: (data) => <DecisionQueue data={data} /> },
  { slug: "platform-assurance", label: "Platform Assurance", icon: ShieldCheck,
    summary: "Each platform control from its own evidence, never averaged.",
    render: (data) => <Assurance data={data} /> },
  { slug: "audit-evidence", label: "Audit & Evidence", icon: FileText,
    summary: "Audit ledger activity, evidence exports and refused access attempts.",
    render: (data) => <EvidenceAudit data={data} /> },
  { slug: "entities-clients", label: "Entities & Clients", icon: Layers, partial: true,
    summary: "Companies and their sign-in activity across the platform.",
    render: (data) => <TenantGovernance data={data} /> },
  { slug: "tenant-isolation", label: "Tenant Isolation", icon: Lock,
    summary: "Row-level isolation between tenants and the absence of standing data access.",
    render: (data) => <><Assurance data={data} keys={/^isolation$/} /><TenantGovernance data={data} /></> },
  { slug: "support-access", label: "Support Access", icon: Eye, partial: true,
    summary: "Support reaches tenant data only through approved, time-limited emergency access.",
    render: (data) => <><PrivilegedAccess data={data} /><DecisionQueue data={data} areas={/Privileged access/} /></> },
  { slug: "ai-safety-dashboard", label: "AI Safety Dashboard", icon: ShieldCheck, partial: true,
    summary: "Kriton evaluation and release gates across the platform.",
    render: (data) => <><Assurance data={data} keys={/^(evaluation|releases)$/} /><KritonControlPlane data={data} /></> },
  { slug: "model-prompt-registry", label: "Model & Prompt Registry", icon: Cpu, partial: true,
    summary: "Model and prompt versions behind Kriton releases.",
    render: (data) => <KritonControlPlane data={data} /> },
  { slug: "evaluation-gates", label: "Evaluation Gates", icon: CircleCheck,
    summary: "The latest Kriton evaluation runs and their metrics.",
    render: (data) => <><Assurance data={data} keys={/^evaluation$/} /><KritonControlPlane data={data} /></> },
  { slug: "source-license-controls", label: "Source & License Controls", icon: FileText, partial: true,
    summary: "Source integrity behind Kriton answers.",
    render: (data) => <KritonControlPlane data={data} /> },
  { slug: "release-gates", label: "Release Gates", icon: Zap,
    summary: "Release candidates, holds and the decisions they wait on.",
    render: (data) => <><Assurance data={data} keys={/^releases$/} /><DecisionQueue data={data} areas={/^Release$/} /><KritonControlPlane data={data} /></> },
  { slug: "incident-response", label: "Incident Response", icon: TriangleAlert,
    summary: "Open security incidents waiting for a decision.",
    render: (data) => <DecisionQueue data={data} areas={/Security incident/} /> },
  { slug: "privileged-access", label: "Privileged Access", icon: Lock,
    summary: "Emergency access requests, active grants and post-access reviews.",
    render: (data) => <><Assurance data={data} keys={/^privileged$/} /><PrivilegedAccess data={data} /><DecisionQueue data={data} areas={/Privileged access/} /></> },
  { slug: "status-health", label: "Status & Health", icon: Activity,
    summary: "Service health, availability and response times.",
    render: (data) => <><Assurance data={data} keys={/^resilience$/} /><Reliability data={data} /></> },
  { slug: "provider-register", label: "Provider Register", icon: Server,
    summary: "Provider risk reviews and blocked providers.",
    render: (data) => <><Assurance data={data} keys={/^providers$/} /><DecisionQueue data={data} areas={/Provider risk/} /></> },
  { slug: "integrations", label: "Integrations", icon: Link2, partial: true,
    summary: "Health of the services the platform depends on.",
    render: (data) => <Reliability data={data} /> },
  { slug: "billing-assurance", label: "Billing Assurance", icon: Wallet,
    summary: "Statement totals, disputes and pending credits.",
    render: (data) => <><Assurance data={data} keys={/^billing$/} /><CommercialAssurance data={data} /><DecisionQueue data={data} areas={/Billing assurance/} /></> },
  { slug: "usage-metering", label: "Usage & Metering", icon: BarChart3, partial: true,
    summary: "Metering disputes and their effect on charges.",
    render: (data) => <><CommercialAssurance data={data} /><DecisionQueue data={data} areas={/Billing assurance/} /></> },
  { slug: "finance-reconciliation", label: "Finance & Reconciliation", icon: Coins, partial: true,
    summary: "Invoiced, collected and receivable totals for the month.",
    render: (data) => <CommercialAssurance data={data} /> },
  { slug: "roles-permissions", label: "Roles & Permissions", icon: UserCog, partial: true,
    summary: "Who holds which role; open Users & Teams for every account and its role.",
    render: (data) => <TenantGovernance data={data} /> },
  { slug: "service-accounts", label: "Service Accounts", icon: Lock, partial: true,
    summary: "Non-human accounts and their access.",
    render: (data) => <><Assurance data={data} keys={/^(isolation|privileged)$/} /><EvidenceAudit data={data} /></> },
  { slug: "tenant-settings", label: "Tenant Settings", icon: Settings, partial: true,
    summary: "Platform-level settings for tenants.",
    render: (data) => <TenantGovernance data={data} /> },
];

/** Live counts beside sidebar entries, by href, from the platform command
 * data: `attention` marks something waiting on someone; zero is not shown. */
export type NavCount = { count: number; attention: boolean };
export function navCounts(data: PlatformCommand): Record<string, NavCount> {
  const s = data.summary;
  const exceptions = data.controls.filter((c) => c.state === "fail" || c.state === "review").length;
  const area = (pattern: RegExp) => data.decisions.filter((d) => pattern.test(d.area)).length;
  const attention = (count: number): NavCount => ({ count, attention: true });
  const counts: Record<string, NavCount> = {
    "/super-admin": attention(s.controlExceptions),
    "/super-admin/executive-decisions": attention(data.decisions.length),
    "/super-admin/platform-assurance": attention(exceptions),
    "/super-admin/audit-evidence": attention(data.audit.exportsPending),
    "/super-admin/companies": { count: data.tenants.total, attention: false },
    "/super-admin/support-access": attention(data.privileged.active),
    "/super-admin/evaluation-gates": attention(data.evaluation.recent.failed),
    "/super-admin/release-gates": attention(s.releaseHolds),
    "/super-admin/incident-response": attention(s.openIncidents),
    "/super-admin/privileged-access": attention(s.privilegedRequests),
    "/super-admin/status-health": attention(data.health.degraded),
    "/super-admin/provider-register": attention(area(/Provider risk/)),
    "/super-admin/billing-assurance": attention(data.commercial.openDisputes),
    "/super-admin/usage-metering": attention(data.commercial.openDisputes),
    "/super-admin/accounts": { count: data.tenants.users, attention: false },
  };
  return Object.fromEntries(Object.entries(counts).filter(([, value]) => value.count > 0));
}

const section = (slug: string): NavEntry => {
  const s = SECTIONS.find((x) => x.slug === slug)!;
  return { label: s.label, icon: s.icon, href: `/super-admin/${s.slug}` };
};

export const NAV: { section: string; items: NavEntry[] }[] = [
  { section: "Platform command", items: [
    { label: "Super Admin Command", icon: LayoutGrid, href: "/super-admin" },
    section("executive-decisions"), section("platform-assurance"), section("audit-evidence"),
  ] },
  { section: "Tenant governance", items: [
    { label: "Tenant Registry", icon: Users, href: "/super-admin/companies" },
    section("entities-clients"), section("tenant-isolation"), section("support-access"),
  ] },
  { section: "Kriton governance", items: [
    section("ai-safety-dashboard"), section("model-prompt-registry"), section("evaluation-gates"),
    section("source-license-controls"), section("release-gates"),
  ] },
  { section: "Security & operations", items: [
    section("incident-response"), section("privileged-access"), section("status-health"), section("provider-register"), section("integrations"),
  ] },
  { section: "Commercial management", items: [
    section("billing-assurance"), section("usage-metering"), section("finance-reconciliation"),
  ] },
  { section: "Administration", items: [
    section("roles-permissions"),
    { label: "Users & Teams", icon: Users, href: "/super-admin/accounts" },
    section("service-accounts"), section("tenant-settings"),
  ] },
];
