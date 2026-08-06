import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PersonalizationConsent, PersonalizationSummary } from "@/lib/api";

const disabledConsent: PersonalizationConsent = {
  personalization_enabled: false, personalization_scope: "visualization_only", personalization_history_window: "90_days",
  allow_view_switch_learning: true, allow_export_learning: true, allow_save_learning: true, schema_version: "1.0",
};

const enabledConsent: PersonalizationConsent = { ...disabledConsent, personalization_enabled: true };

const collectingSummary: PersonalizationSummary = {
  eligible: false, interaction_count: 3, conversation_count: 1, top_family_preferences: {}, top_intent_preferences: {},
};

const eligibleSummary: PersonalizationSummary = {
  eligible: true, interaction_count: 18, conversation_count: 5,
  top_family_preferences: { two_point_per_entity: "dumbbell" }, top_intent_preferences: { trend: "line" },
};

let currentConsent = disabledConsent;
let currentSummary = collectingSummary;
const putCalls: PersonalizationConsent[] = [];
const resetCalls: number[] = [];
const deleteCalls: number[] = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    getPersonalizationConsent: vi.fn(async () => currentConsent),
    getPersonalizationSummary: vi.fn(async () => currentSummary),
    putPersonalizationConsent: vi.fn(async (_token: string, value: PersonalizationConsent) => {
      putCalls.push(value);
      currentConsent = value;
      return value;
    }),
    resetPersonalizationProfile: vi.fn(async () => { resetCalls.push(1); }),
    deletePersonalizationProfile: vi.fn(async () => { deleteCalls.push(1); }),
  };
});

const { default: VisualizationPersonalizationPage } = await import("@/app/visualization-personalization/page");

describe("Visualization Personalization settings page", () => {
  it("shows personalization as off by default", async () => {
    currentConsent = disabledConsent;
    currentSummary = collectingSummary;
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByLabelText("Enable personalized recommendations")).toBeTruthy());
    const checkbox = screen.getByLabelText("Enable personalized recommendations") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
    expect(screen.getByText(/Personalization is off/)).toBeTruthy();
  });

  it("enabling personalization calls the API with enabled=true", async () => {
    currentConsent = disabledConsent;
    putCalls.length = 0;
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByLabelText("Enable personalized recommendations")).toBeTruthy());
    fireEvent.click(screen.getByLabelText("Enable personalized recommendations"));
    await waitFor(() => expect(putCalls.length).toBeGreaterThan(0));
    expect(putCalls[0].personalization_enabled).toBe(true);
  });

  it("shows 'Collecting evidence' below the minimum-evidence threshold", async () => {
    currentConsent = enabledConsent;
    currentSummary = collectingSummary;
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByText(/Collecting evidence/)).toBeTruthy());
  });

  it("shows the learned summary sentence once eligible", async () => {
    currentConsent = enabledConsent;
    currentSummary = eligibleSummary;
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByText(/Across 18 eligible interactions/)).toBeTruthy());
    expect(screen.getByText(/line charts for trend/)).toBeTruthy();
  });

  it("never renders detailed event history, only counts and chart-type labels", async () => {
    currentConsent = enabledConsent;
    currentSummary = eligibleSummary;
    const { container } = render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByText(/Across 18 eligible interactions/)).toBeTruthy());
    const html = container.innerHTML;
    expect(html).not.toContain("query_id");
    expect(html).not.toContain("actor_id");
  });

  it("clicking 'Reset learned recommendations' calls the reset endpoint", async () => {
    currentConsent = enabledConsent;
    currentSummary = eligibleSummary;
    resetCalls.length = 0;
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByText("Reset learned recommendations")).toBeTruthy());
    fireEvent.click(screen.getByText("Reset learned recommendations"));
    await waitFor(() => expect(resetCalls.length).toBeGreaterThan(0));
  });

  it("clicking 'Disable and delete profile' calls the delete endpoint", async () => {
    currentConsent = enabledConsent;
    currentSummary = eligibleSummary;
    deleteCalls.length = 0;
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByText("Disable and delete profile")).toBeTruthy());
    fireEvent.click(screen.getByText("Disable and delete profile"));
    await waitFor(() => expect(deleteCalls.length).toBeGreaterThan(0));
  });

  it("shows a friendly error instead of crashing when loading settings fails", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.getPersonalizationConsent).mockRejectedValueOnce(new Error("500"));
    render(<VisualizationPersonalizationPage />);
    await waitFor(() => expect(screen.getByText(/Could not load personalization settings/)).toBeTruthy());
  });
});
