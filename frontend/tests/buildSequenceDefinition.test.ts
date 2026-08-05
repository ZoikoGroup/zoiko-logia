import { describe, expect, it } from "vitest";
import { buildSequenceDefinition } from "@/components/WorkflowVisualization";

describe("buildSequenceDefinition", () => {
  it("attributes a generic processing verb to its actual actor, not the fallback", () => {
    // Reproduces the live case: "processes" wasn't in the original
    // message-passing-only verb list, so this step fell back to a note on
    // "Kriton" instead of "The classifier".
    const definition = buildSequenceDefinition([
      "The classifier receives input data, such as financial information or tax-related data.",
      "The classifier processes the input data and identifies relevant information, such as revenue recognition or depreciation methods.",
      "The classifier sends the processed data to the calculation engine.",
    ]);

    expect(definition).not.toMatch(/Note over p\d+: The classifier processes/);
    // Step 2 has no explicit "to X" — it should render as a self-note on
    // the classifier's own lane, with the actor name itself never repeated
    // inside the message (the lane label already carries it).
    const classifierId = /participant (p\d+) as "The classifier"/.exec(definition)?.[1];
    expect(classifierId).toBeDefined();
    expect(definition).toContain(`Note over ${classifierId}: processes the input data`);
  });

  it("continues attributing an unparseable fragment to the previously addressed actor", () => {
    const definition = buildSequenceDefinition([
      "The classifier sends the query to the Calculation Engine.",
      "runs a full validation pass before responding.", // no leading actor — should continue as Calculation Engine
    ]);
    const engineId = /participant (p\d+) as "Calculation Engine"/.exec(definition)?.[1];
    expect(engineId).toBeDefined();
    expect(definition).toContain(`Note over ${engineId}: runs a full validation pass before responding.`);
  });

  it("renders an arrow to a lowercase, article-prefixed target (\"to the calculation engine\")", () => {
    // English infinitives never take an article ("to the run" isn't valid
    // English), so "to the/a/an <phrase>" is safe to treat as an actor
    // target even when — as is common in prose — it isn't capitalized.
    const definition = buildSequenceDefinition([
      "The classifier sends the processed data to the calculation engine.",
    ]);
    const classifierId = /participant (p\d+) as "The classifier"/.exec(definition)?.[1];
    const engineId = /participant (p\d+) as "calculation engine"/.exec(definition)?.[1];
    expect(classifierId).toBeDefined();
    expect(engineId).toBeDefined();
    expect(definition).toContain(`${classifierId}->>${engineId}: sends the processed data`);
  });

  it("does not mistake an ordinary infinitive phrase for an actor target", () => {
    const definition = buildSequenceDefinition([
      "The classifier processes the query to calculate the risk score.",
    ]);
    // No article before "calculate" — this is a bare infinitive, not a
    // target reference, so it must not become a second participant.
    expect(definition).not.toMatch(/participant p\d+ as "calculate/);
  });

  it("attributes audit-domain verbs (assess/document/escalate/...) to their actual actor", () => {
    // Live bug: the verb list only covered message-passing/generic
    // processing verbs, so an auditor's judgment steps ("assesses",
    // "documents", "escalates") all fell to the "Kriton" fallback note
    // instead of the auditor/management/reviewer actors already named.
    const definition = buildSequenceDefinition([
      "The auditor assesses the significance of the exception.",
      "The auditor documents the conclusion in the working papers.",
      "The auditor escalates the exception to management.",
      "Management responds to the escalation with a proposed correction.",
    ]);
    expect(definition).not.toMatch(/Note over p\d+: The auditor/);
    expect(definition).not.toMatch(/Note over p\d+: Management/);
    const auditorId = /participant (p\d+) as "The auditor"/.exec(definition)?.[1];
    const managementId = /participant (p\d+) as "management"/.exec(definition)?.[1];
    expect(auditorId).toBeDefined();
    expect(managementId).toBeDefined();
    expect(definition).toContain(`Note over ${auditorId}: assesses the significance of the exception.`);
    expect(definition).toContain(`${auditorId}->>${managementId}: escalates the exception`);
  });

  it("extracts a target before a colon and keeps the detail in the message", () => {
    const definition = buildSequenceDefinition([
      "Validation service sends validated invoice data to the duplicate checker: Confirm required fields and arithmetic.",
    ]);
    const source = /participant (p\d+) as "Validation service"/.exec(definition)?.[1];
    const target = /participant (p\d+) as "duplicate checker"/.exec(definition)?.[1];
    expect(source).toBeDefined();
    expect(target).toBeDefined();
    expect(definition).toContain(`${source}->>${target}: sends validated invoice data — Confirm required fields and arithmetic.`);
  });
});
