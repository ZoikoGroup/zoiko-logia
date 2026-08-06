"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import mermaid from "mermaid";
import {
  addEdge, Background, Controls, ReactFlow, useEdgesState, useNodesState,
  type Connection, type Edge, type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { PresentationGuide } from "@/lib/api";
import { VisualizationActions } from "@/components/VisualizationActions";
import { exportMermaidPng } from "@/lib/export/exportMermaidPng";
import { exportWorkflowPng } from "@/lib/export/exportWorkflowPng";
import { saveVisualization } from "@/lib/export/saveVisualization";

function safeLabel(value: string): string {
  return value.replace(/["<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 180);
}

// Message-passing verbs (send/receive/...) plus general processing verbs
// (process/validate/compute/...) — a validated step describing what an
// actor internally does, not just what it sends, is at least as common in
// prose as an explicit handoff, and previously fell through to the
// fallback-actor note below instead of being attributed correctly.
const _SEQUENCE_STEP_VERBS =
  "sends?|calls?|requests?|returns?|responds?(?:\\s+to)?|forwards?|receives?|queries?|invokes?|" +
  "notifies?|passes?|routes?|processes?|validates?|computes?|calculates?|checks?|verifies?|" +
  "generates?|analyzes?|transforms?|evaluates?|identifies?|determines?|applies?|updates?|" +
  "records?|assigns?|reviews?|prepares?|extracts?|derives?|handles?|executes?|performs?|" +
  // Audit/business-process verbs — a step describing an auditor/reviewer's
  // judgment or a workflow's approval action is at least as common as a
  // message handoff, and previously fell to the "Kriton" fallback note
  // instead of the auditor/management/reviewer actor already named earlier
  // in the same sentence.
  "assesses?|concludes?|documents?|escalates?|communicates?|discusses?|consults?|obtains?|" +
  "confirms?|investigates?|resolves?|reports?|approves?|rejects?|authorizes?|signs?|flags?|" +
  "raises?|closes?|files?|submits?|reconciles?|matches?|corroborates?|inspects?|observes?|" +
  "interviews?|tests?|samples?|adjusts?";
const _SEQUENCE_STEP_PATTERN = new RegExp(`^([A-Z][\\w\\s]{1,28}?)\\s+(${_SEQUENCE_STEP_VERBS})\\s+(.+)$`);

/** Extracts an "Actor verb ... to Actor" shape from a validated step sentence
 * without inventing any actor the sentence doesn't already name. A step that
 * doesn't match the shape (e.g. a sentence fragment continuing the previous
 * one) becomes a self-note on whichever actor the previous step last
 * addressed, rather than an unrelated placeholder — narrative continuation
 * is a better default than a fixed fallback name for an unparseable step. */
/** Actor references at the end of a sentence ("...to the calculation
 * engine.") are just as often a lowercase common-noun phrase as a
 * capitalized proper noun — but a bare "to <lowercase word>" is also how
 * ordinary infinitive phrases read ("needs to calculate the total"), which
 * are never actor references. The distinguishing signal is the article:
 * English infinitives never take one ("to the run" isn't valid), so "to
 * the/a/an <phrase>" is safe to treat as a target even in lowercase, while
 * a bare "to <word>" still requires the capital-letter proper-noun form. */
// A closed vocabulary rather than a generic "bare lowercase word" rule — a
// role/department name ("escalates ... to management") is commonly written
// without an article or capital, but a generic rule would also swallow
// ordinary infinitive tails ("needs to calculate the total"). Listing the
// specific words is safer than trying to distinguish the two generically.
const _SEQUENCE_BARE_ROLE_TARGET = "[Mm]anagement|[Cc]ompliance|[Aa]ccounting|[Ff]inance|[Tt]reasury|[Ll]egal|[Tt]he board|[Tt]he committee";
const _SEQUENCE_TARGET_PATTERN = new RegExp(
  "\\bto\\s+(?:(?:the|a|an)\\s+([a-zA-Z][\\w\\s-]{1,34}?)|(" + _SEQUENCE_BARE_ROLE_TARGET + ")|([A-Z][\\w\\s-]{1,34}?))(?=\\s*(?::|[.,]?$))",
);

/** Actor names are deduplicated with a leading article stripped, so "The
 * calculation engine" (sentence-initial) and "the calculation engine"
 * (captured after "to") land on the same participant lane instead of two. */
function canonicalActorKey(name: string): string {
  return name.replace(/^(the|a|an)\s+/i, "").trim().toLowerCase();
}

function parseSequenceStep(
  text: string,
  previousActor: string,
): { from: string; to: string; message: string } {
  const stepMatch = text.match(_SEQUENCE_STEP_PATTERN);
  if (!stepMatch) return { from: previousActor, to: previousActor, message: text };
  const from = stepMatch[1].trim();
  const verb = stepMatch[2].trim();
  const rest = stepMatch[3].trim();
  const toMatch = rest.match(_SEQUENCE_TARGET_PATTERN);
  if (!toMatch) return { from, to: from, message: `${verb} ${rest}`.trim() };
  const to = (toMatch[1] ?? toMatch[2] ?? toMatch[3]).trim();
  const beforeTarget = rest.slice(0, toMatch.index ?? 0).trim();
  let detail = rest.slice((toMatch.index ?? 0) + toMatch[0].length).replace(/^\s*:\s*/, "— ").trim();
  if (/^[.,]$/.test(detail)) detail = "";
  const message = [verb, beforeTarget, detail].filter(Boolean).join(" ").trim() || verb;
  return { from, to, message };
}

export function buildSequenceDefinition(items: string[]): string {
  let previousActor = "Kriton";
  const steps = items.map((item) => {
    const step = parseSequenceStep(item, previousActor);
    previousActor = step.to;
    return step;
  });
  const idByActor = new Map<string, string>();
  const participants: string[] = [];
  const ensureActor = (name: string) => {
    const key = canonicalActorKey(name);
    if (!idByActor.has(key)) {
      idByActor.set(key, `p${idByActor.size}`);
      participants.push(name);
    }
    return idByActor.get(key)!;
  };
  steps.forEach((step) => {
    ensureActor(step.from);
    ensureActor(step.to);
  });
  const lines = [
    "sequenceDiagram",
    ...participants.map((name) => `participant ${idByActor.get(canonicalActorKey(name))} as "${safeLabel(name)}"`),
  ];
  steps.forEach((step) => {
    const fromId = idByActor.get(canonicalActorKey(step.from))!;
    const toId = idByActor.get(canonicalActorKey(step.to))!;
    const message = safeLabel(step.message || "step");
    lines.push(fromId === toId ? `Note over ${fromId}: ${message}` : `${fromId}->>${toId}: ${message}`);
  });
  return lines.join("\n");
}

function MermaidGuide({
  guide, queryId, sourceReferences = [],
}: {
  guide: PresentationGuide;
  queryId?: string;
  sourceReferences?: string[];
}) {
  const reactId = useId().replace(/:/g, "");
  const [svg, setSvg] = useState("");
  const idempotencyKeyRef = useRef(crypto.randomUUID());
  const definition = useMemo(() => {
    if (guide.type === "sequence") return buildSequenceDefinition(guide.items);
    const direction = guide.type === "timeline" ? "LR" : "TD";
    const nodes = guide.items.map((item, index) => `n${index}["${index + 1}. ${safeLabel(item)}"]`);
    const links = guide.items.slice(1).map((_, index) => `n${index} --> n${index + 1}`);
    return [`flowchart ${direction}`, ...nodes, ...links].join("\n");
  }, [guide]);

  useEffect(() => {
    let active = true;
    // htmlLabels: false forces node/actor text to render as native SVG
    // <text> instead of <foreignObject><div>...</div></foreignObject>. Without
    // this, Chromium/Firefox/Safari all treat the rendered SVG as "tainted"
    // when it's later drawn to a <canvas> via an <img> for PNG export (see
    // exportMermaidPng.ts) — canvas.toBlob() then throws SecurityError
    // regardless of the blob: URL being same-origin, because a foreignObject
    // is spec-ambiguous for cross-origin purposes. This is an export-safety
    // setting, not a security boundary we're relying on.
    mermaid.initialize({
      startOnLoad: false, securityLevel: "strict", theme: "base",
      htmlLabels: false, flowchart: { htmlLabels: false },
      // mirrorActors repeats every participant box at the bottom of the
      // diagram (standard UML notation), which read as "duplicated actors"
      // to someone unfamiliar with sequence-diagram conventions — one set
      // of boxes at the top is enough here.
      sequence: { mirrorActors: false },
    });
    mermaid.render(`kriton-${reactId}`, definition).then(({ svg: rendered }) => {
      if (active) setSvg(rendered);
    }).catch(() => { if (active) setSvg(""); });
    return () => { active = false; };
  }, [definition, reactId]);

  if (!svg) return <p className="p-4 text-xs text-muted">Preparing validated diagram…</p>;
  return (
    <div>
      <div className="overflow-x-auto p-4 [&_svg]:mx-auto [&_svg]:max-w-full" role="img" aria-label={guide.title} dangerouslySetInnerHTML={{ __html: svg }} />
      <div className="border-t border-line px-4 py-3">
        <VisualizationActions
          onDownloadPng={() => exportMermaidPng(svg, guide.title)}
          onSave={
            queryId
              ? async () => {
                  const ok = await saveVisualization(
                    {
                      query_id: queryId,
                      visualization_type: "diagram",
                      title: guide.title,
                      summary: guide.title,
                      payload: guide,
                      source_references: sourceReferences,
                    },
                    idempotencyKeyRef.current,
                  );
                  if (ok) idempotencyKeyRef.current = crypto.randomUUID();
                  return ok;
                }
              : undefined
          }
        />
      </div>
    </div>
  );
}

function EditableFlow({
  guide, queryId, sourceReferences = [],
}: {
  guide: PresentationGuide;
  queryId?: string;
  sourceReferences?: string[];
}) {
  const initialNodes = useMemo<Node[]>(() => guide.flow_nodes?.length ? guide.flow_nodes.map((node) => ({
    id: node.id, position: node.position, data: { label: node.label },
  })) : guide.items.map((item, index) => ({
    id: `step-${index + 1}`, position: { x: (index % 3) * 250, y: Math.floor(index / 3) * 130 },
    data: { label: item },
  })), [guide.flow_nodes, guide.items]);
  const initialEdges = useMemo<Edge[]>(() => guide.flow_edges?.length ? guide.flow_edges : guide.items.slice(1).map((_, index) => ({
    id: `edge-${index + 1}`, source: `step-${index + 1}`, target: `step-${index + 2}`,
  })), [guide.flow_edges, guide.items]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selected, setSelected] = useState<string | null>(null);
  const idempotencyKeyRef = useRef(crypto.randomUUID());
  const selectedNode = nodes.find((node) => node.id === selected);
  const onConnect = (connection: Connection) => setEdges((current) => addEdge(connection, current));
  const addStep = () => setNodes((current) => [...current, { id: `draft-${Date.now()}`, position: { x: 40, y: 40 }, data: { label: "New draft step" } }]);
  const deleteSelected = () => {
    if (!selected) return;
    setNodes((current) => current.filter((node) => node.id !== selected));
    setEdges((current) => current.filter((edge) => edge.source !== selected && edge.target !== selected));
    setSelected(null);
  };
  const updateLabel = (label: string) => setNodes((current) => current.map((node) => node.id === selected ? { ...node, data: { ...node.data, label } } : node));

  return <div>
    <div className="flex flex-wrap gap-2 border-b border-line p-3">
      <button type="button" onClick={addStep} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold">Add step</button>
      <button type="button" onClick={deleteSelected} disabled={!selected} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold disabled:opacity-40">Delete selected</button>
      {selectedNode && <input value={String(selectedNode.data.label ?? "")} onChange={(event) => updateLabel(event.target.value)} aria-label="Selected workflow step label" className="min-w-52 flex-1 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs" />}
      <span className="self-center text-[10px] text-muted">Draft edits are local and do not change governed evidence.</span>
    </div>
    <div className="h-[420px]">
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, node) => setSelected(node.id)} fitView>
        <Background /><Controls />
      </ReactFlow>
    </div>
    <div className="border-t border-line px-4 py-3">
      <VisualizationActions
        onDownloadPng={() => exportWorkflowPng(nodes, edges, guide.title)}
        onSave={queryId ? async () => {
          const editedGuide: PresentationGuide = {
            ...guide,
            items: nodes.map((node) => String(node.data.label ?? "")),
            flow_nodes: nodes.map((node) => ({ id: node.id, position: node.position, label: String(node.data.label ?? "") })),
            flow_edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
          };
          const ok = await saveVisualization({
            query_id: queryId, visualization_type: "diagram", title: guide.title,
            summary: `${nodes.length} editable workflow steps`, payload: editedGuide,
            source_references: sourceReferences,
          }, idempotencyKeyRef.current);
          if (ok) idempotencyKeyRef.current = crypto.randomUUID();
          return ok;
        } : undefined}
      />
    </div>
  </div>;
}

export function WorkflowVisualization({
  guide, queryId, sourceReferences,
}: {
  guide: PresentationGuide;
  queryId?: string;
  sourceReferences?: string[];
}) {
  return guide.renderer === "react_flow"
    ? <EditableFlow guide={guide} queryId={queryId} sourceReferences={sourceReferences} />
    : <MermaidGuide guide={guide} queryId={queryId} sourceReferences={sourceReferences} />;
}
