/**
 * Checks for AnswerRenderer.sanitizeMermaid, over diagrams captured from live
 * model output.
 *
 *   node components/__tests__/sanitize-mermaid.mjs
 *
 * What this DOES prove: the labels that break Mermaid get quoted, the structure
 * of the diagram survives, and diagrams that already worked are left untouched.
 *
 * What it does NOT prove: that Mermaid then accepts the result. Mermaid's own
 * parser needs a browser DOM (it fails in Node with "DOMPurify.addHook is not a
 * function"), and adding jsdom purely to test this is not worth a new
 * dependency. The parse itself is confirmed in the browser.
 *
 * Keep the logic here in step with AnswerRenderer.sanitizeMermaid.
 */

const LABEL_NEEDS_QUOTING = /[()&:;,%#=|]/;

const NODE_SHAPES = [
  [/([A-Za-z0-9_-]+)\(\(([^()\n]*)\)\)/g, "((", "))"],
  [/([A-Za-z0-9_-]+)\[\[([^[\]\n]*)\]\]/g, "[[", "]]"],
  [/([A-Za-z0-9_-]+)\[\(([^[\]\n]*)\)\]/g, "[(", ")]"],
  [/([A-Za-z0-9_-]+)\[([^[\]\n]*)\]/g, "[", "]"],
  [/([A-Za-z0-9_-]+)\{([^{}\n]*)\}/g, "{", "}"],
];

function quoteNodeLabels(src) {
  let out = src;
  for (const [pattern, open, close] of NODE_SHAPES) {
    out = out.replace(pattern, (whole, id, label) => {
      const trimmed = label.trim();
      if (!trimmed || /^".*"$/.test(trimmed) || !LABEL_NEEDS_QUOTING.test(trimmed)) {
        return whole;
      }
      return `${id}${open}"${trimmed.replace(/"/g, "'")}"${close}`;
    });
  }
  return out;
}

function sanitizeMermaid(raw) {
  let c = raw.trim();
  c = c.replace(/^mermaid\s+/i, "");
  c = c.replace(/\|\s*>/g, "|");
  c = c.replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
  c = c.replace(/[\u00a0\u202f\u2007\u2009]/g, " ");
  c = quoteNodeLabels(c);
  return c;
}

let failed = 0;
function check(label, condition, detail) {
  if (!condition) failed++;
  console.log(`${condition ? "PASS" : "FAIL"}  ${label}`);
  if (!condition && detail) console.log(`        ${detail}`);
}

// ── The diagram from the screenshot, which rendered as raw code ─────────────

const SCREENSHOT = `flowchart TD
    A[Zoiko Trading Ltd - Management Accounts (Year ended 31 Mar 2026)] --> B[Page 1 - Profit & Loss Account]
    A --> C[Page 2 - Balance Sheet Extract]
    D --> D1[1. Going concern]`;

const fixed = sanitizeMermaid(SCREENSHOT);
check(
  "screenshot: parenthesised label is quoted",
  fixed.includes('A["Zoiko Trading Ltd - Management Accounts (Year ended 31 Mar 2026)"]'),
  fixed.split("\n")[1]
);
check(
  "screenshot: ampersand label is quoted",
  fixed.includes('B["Page 1 - Profit & Loss Account"]'),
  fixed.split("\n")[1]
);
check(
  "screenshot: clean label left alone",
  fixed.includes("C[Page 2 - Balance Sheet Extract]")
);
check(
  "screenshot: numbered label left alone",
  fixed.includes("D1[1. Going concern]")
);
check("screenshot: arrows preserved", (fixed.match(/-->/g) || []).length === 3);
check("screenshot: header preserved", fixed.startsWith("flowchart TD"));

// ── Other shapes seen in live output ───────────────────────────────────────

check(
  "percent in a label is quoted",
  sanitizeMermaid("flowchart TD\n B --> B8[Corporation Tax (25 %)]")
    .includes('B8["Corporation Tax (25 %)"]')
);
check(
  "colon in a label is quoted",
  sanitizeMermaid("flowchart TD\n A[Gross Profit Margin: 41.9%]")
    .includes('A["Gross Profit Margin: 41.9%"]')
);
check(
  "rhombus label is quoted",
  sanitizeMermaid("flowchart TD\n B{Material (per policy)?}")
    .includes('B{"Material (per policy)?"}')
);
check(
  "circle label with ampersand is quoted",
  sanitizeMermaid("flowchart TD\n A((Profit & Loss))").includes('A(("Profit & Loss"))')
);
check(
  "narrow and non-breaking spaces are normalised",
  !/[    ]/.test(
    sanitizeMermaid(`flowchart TD
 A[Tax 25 %]
 B[Total 1 605 000]`)
  )
);
check(
  "double quote inside a label becomes a single quote",
  sanitizeMermaid('flowchart TD\n A[The "big" one (x)]').includes(`A["The 'big' one (x)"]`)
);

// ── Diagrams that already worked must be byte-identical ────────────────────

const UNTOUCHED = {
  "plain flowchart": "flowchart LR\n    A[Start] --> B[Middle]\n    B --> C[End]",
  "already quoted": 'flowchart TD\n    A["Profit & Loss (Page 1)"] --> B["Balance Sheet"]',
  "pie chart": 'pie title Revenue\n    "Software" : 1199000\n    "Hardware" : 553000',
  "question mark only": "flowchart TD\n    B{Is materiality exceeded?}",
  "edge labels": "flowchart TD\n    B -->|Yes| C[Investigate]\n    B -->|No| D[Stop]",
  "br tag in a label": "flowchart TD\n    A[Line one<br/>Line two]",
};
for (const [label, code] of Object.entries(UNTOUCHED)) {
  check(`untouched: ${label}`, sanitizeMermaid(code) === code.trim(), sanitizeMermaid(code));
}

console.log(failed ? `\n${failed} FAILURE(S)` : "\nALL PASS");
process.exit(failed ? 1 : 0);
