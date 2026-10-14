export const METRICS = [
  { label: "Active sources", value: "1,284", detail: "37 due for review" },
  { label: "Pending reviews", value: "42", detail: "11 legal/compliance" },
  { label: "Open escalations", value: "14", detail: "3 over SLA" },
  { label: "Source-drift alerts", value: "9", detail: "4 affect production" },
];


export const LOCALIZATION_CARD = {
  heading: "Localization & accessibility",
  body: "Translation-key UI, terminology review, keyboard focus, screen reader labels, non-color-only status.",
};

// [date, event, category, status]; Upcoming→info, At risk→warn, Overdue→bad
export const COMPLIANCE_CALENDAR: [string, string, string, "Upcoming" | "At risk" | "Overdue"][] = [
  ["Jul 15, 2026", "Quarterly source license renewal review", "Content governance", "Upcoming"],
  ["Aug 1, 2026", "GDPR data processing audit", "Privacy", "Upcoming"],
  ["Aug 20, 2026", "Model card review — Q3", "AI safety", "Upcoming"],
  ["Sep 5, 2026", "SOC 2 Type II renewal", "Compliance", "At risk"],
  ["Sep 30, 2026", "Annual accessibility audit", "Compliance", "Upcoming"],
];



// [gate, status]; Passed→ok, Partial→warn, Pending→neutral
