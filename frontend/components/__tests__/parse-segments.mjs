/**
 * Fence classification checks for AnswerRenderer.parseSegments.
 *
 * The logic is duplicated here rather than imported because AnswerRenderer is a
 * client component with React and mermaid imports; this file exercises the pure
 * decision the segmenter makes. Keep the two in step.
 *
 *   node components/__tests__/parse-segments.mjs
 */

const MERMAID_OPENERS =
  /^\s*(?:%%\{[\s\S]*?\}%%\s*)?(flowchart|graph\s+(?:TB|TD|BT|RL|LR)|sequenceDiagram|classDiagram(?:-v2)?|stateDiagram(?:-v2)?|erDiagram|journey|gantt|pie(?:\s|$)|mindmap|timeline|quadrantChart|gitGraph|sankey-beta|xychart-beta|block-beta|requirementDiagram|C4Context)\b/i;

const UNLABELLED_FENCE = /^(|text|txt|plaintext|plain|markdown|md|mmd)$/i;

function classifyFence(language, body) {
  const lang = language.trim().toLowerCase();
  if (lang === "chart") return "chart";
  if (lang === "mermaid" || lang === "mmd") return "mermaid";
  if (UNLABELLED_FENCE.test(lang) && MERMAID_OPENERS.test(body)) return "mermaid";
  return null;
}

function parseSegments(text) {
  const segments = [];
  const regex = /```([A-Za-z0-9_+-]*)[ \t]*\r?\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    const kind = classifyFence(match[1], match[2]);
    if (!kind) continue;
    if (match.index > lastIndex) {
      segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }
    segments.push({ type: kind, content: match[2].trim() });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", content: text.slice(lastIndex) });
  }
  return segments;
}

// The block from the screenshot: a real flowchart on a bare fence, which used
// to render as monospace text.
const BARE_FLOWCHART = `Structure of the document

\`\`\`
flowchart TD
    A[Management Accounts] --> B[Profit & Loss Account (Page 1)]
    A --> C[Balance Sheet Extract (Page 2)]
\`\`\`
`;

const CASES = [
  ["tagged mermaid", "```mermaid\nflowchart TD\n A-->B\n```", ["mermaid"]],
  ["bare fence, flowchart", BARE_FLOWCHART, ["text", "mermaid", "text"]],
  ["bare fence, pie", "```\npie title Split\n \"A\" : 10\n```", ["mermaid"]],
  ["bare fence, sequenceDiagram", "```\nsequenceDiagram\n A->>B: hi\n```", ["mermaid"]],
  ["bare fence, graph LR", "```\ngraph LR\n A-->B\n```", ["mermaid"]],
  ["bare fence, mindmap", "```\nmindmap\n root((x))\n```", ["mermaid"]],
  ["text-tagged flowchart", "```text\nflowchart TD\n A-->B\n```", ["mermaid"]],
  ["mermaid with init directive",
   "```\n%%{init: {'theme':'base'}}%%\nflowchart TD\n A-->B\n```", ["mermaid"]],
  ["chart block", '```chart\n{"type":"bar"}\n```', ["chart"]],
  // Must NOT be treated as diagrams:
  ["python code stays code", "```python\nprint('flowchart TD')\n```", ["text"]],
  ["sql code stays code", "```sql\nSELECT 1;\n```", ["text"]],
  ["bare fence of prose stays code",
   "```\nRevenue 4,182,000\nCost of sales 2,431,000\n```", ["text"]],
  ["bare fence mentioning pie in prose",
   "```\nthe pie was tasty\n```", ["text"]],
  ["no fences at all", "Just an answer with no code.", ["text"]],
];

let failed = 0;
for (const [label, input, expected] of CASES) {
  const got = parseSegments(input).map((s) => s.type);
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label.padEnd(34)} ${JSON.stringify(got)}`);
  if (!ok) console.log(`      expected ${JSON.stringify(expected)}`);
}

// The screenshot's diagram must survive intact, not just be classified.
const diagram = parseSegments(BARE_FLOWCHART).find((s) => s.type === "mermaid");
const intact = diagram?.content.startsWith("flowchart TD") &&
  diagram.content.includes("Balance Sheet Extract");
console.log(`${intact ? "PASS" : "FAIL"}  diagram body preserved intact`);
if (!intact) failed++;

console.log(failed ? `\n${failed} FAILURE(S)` : "\nALL PASS");
process.exit(failed ? 1 : 0);
