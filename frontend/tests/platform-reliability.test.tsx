import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: { id: "me", role: "Super Admin" } }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import { KritonControlPlane, Reliability } from "@/components/platform/command";
import type { PlatformCommand } from "@/lib/api";

const service = (key: string, name: string, state: string, core = false) =>
  ({ key, name, state, core, latencyMs: state === "operational" ? 120 : null, checkedAt: "2026-11-04T10:00:00Z" });

// The Super Admin screenshot of 4 Nov: four measured services up, six optional
// ones with no settings on the server.
function command(services: ReturnType<typeof service>[], degraded: number, coreDown: string[] = []) {
  const measured = services.filter((s) => s.state !== "not_configured").length;
  return {
    summary: { availabilityPct: 100 },
    health: { services, sampled: true, availabilityPct: 100, objectivePct: 99.9, p95LatencyMs: 660, degraded, measured, coreDown },
  } as unknown as PlatformCommand;
}

const configuredUp = [
  service("supabase_auth", "Authentication", "operational", true),
  service("database", "Database", "operational", true),
  service("api", "Kriton API", "operational", true),
  service("groq", "Groq", "operational"),
];
const notConfigured = ["Anthropic", "Background jobs", "Diagrams", "Google Gemini", "OpenAI", "Web search"]
  .map((name) => service(name.toLowerCase(), name, "not_configured"));

describe("Reliability panel", () => {
  it("shows no warning when only optional services are not configured", () => {
    render(<Reliability data={command([...notConfigured, ...configuredUp], 0)} />);
    expect(screen.queryByText(/6 services not operational/i)).toBeNull();
    expect(screen.getByText("0 / 4")).toBeTruthy();
    expect(screen.getAllByText("Not configured")).toHaveLength(6);
  });

  it("warns about a configured service that is down, and counts only that one", () => {
    const down = [service("groq", "Groq", "down"), ...configuredUp.slice(0, 3)];
    render(<Reliability data={command([...down, ...notConfigured], 1)} />);
    expect(screen.getByText(/Down · Groq/)).toBeTruthy();
    expect(screen.getByText(/^1 service not operational$/)).toBeTruthy();
  });

  it("keeps the three states apart in totals that add up, and shows each check's result", () => {
    const data = command([...notConfigured, ...configuredUp.map((s) => ({ ...s, detail: "HTTP 200" }))], 0);
    data.health.counts = { operational: 4, notConfigured: 6, down: 0, unchecked: 1, total: 11 };
    render(<Reliability data={data} />);
    expect(screen.getByTestId("service-counts").textContent).toBe(
      "11 services: 4 operational · 6 not configured · 0 down · 1 not checked in the last 15 minutes");
    expect(screen.getAllByText("HTTP 200")).toHaveLength(4);
  });
});

describe("Kriton AI Control Plane", () => {
  it("says why the status is Unknown when no evaluation run is recorded", () => {
    const data = {
      generatedAt: "2026-11-04T10:00:00Z",
      releases: { open: 0, held: 0, items: [] },
      evaluation: { state: "unknown", latest: null, metrics: [], recent: { completed: 0, failed: 0 },
                    reason: "No evaluation run is recorded yet" },
    } as unknown as PlatformCommand;
    render(<KritonControlPlane data={data} />);
    expect(screen.getByText("No evaluation run is recorded yet, so the status is Unknown.")).toBeTruthy();
  });
});
