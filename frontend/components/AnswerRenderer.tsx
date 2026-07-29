"use client";

import { useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders a Kriton answer. Text is rendered as Markdown (so tables, bullet
 * lists, bold, and headings display properly, like ChatGPT), while any fenced
 * ```mermaid code block is rendered as a visual diagram (flowchart, workflow,
 * sequence, etc.). Citations, risk badge and everything else are unchanged.
 */

type Segment = { type: "text"; content: string } | { type: "mermaid"; content: string };

/**
 * Safety net: strip any inline citation markers the model still slips into the
 * answer text (e.g. "[REF-1]", "[REF-2, REF-5]", "[1]"). Sources are shown in
 * the separate Sources panel, so the answer body should read cleanly. Also
 * tidies up the leftover spaces/punctuation the removal leaves behind.
 */
function stripInlineRefs(text: string): string {
  return text
    .replace(/\s*\[\s*(?:REF-)?\d+(?:\s*,\s*(?:REF-)?\d+)*\s*\]/gi, "")
    .replace(/[ \t]+([.,;:])/g, "$1")
    .replace(/[ \t]{2,}/g, " ");
}

function parseSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  const regex = /```mermaid\s*([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }
    segments.push({ type: "mermaid", content: match[1].trim() });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", content: text.slice(lastIndex) });
  }
  return segments;
}

/**
 * Repair the most common Mermaid mistakes LLMs make, so a small slip doesn't
 * blow up the whole diagram into a syntax error.
 */
function sanitizeMermaid(raw: string): string {
  let c = raw.trim();
  // Strip a stray leading "mermaid" language tag if the model added one.
  c = c.replace(/^mermaid\s+/i, "");
  // Most common error: an edge label written as `-->|Yes|>` (extra `>`) or
  // `-->|Yes|-->` instead of the valid `-->|Yes|`.
  c = c.replace(/\|\s*>/g, "|");
  // Curly/smart quotes inside labels break the parser — normalise them.
  c = c.replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
  return c;
}

function MermaidDiagram({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Dynamic import so mermaid (which touches the DOM) never runs on the server.
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "strict",
          // Don't let mermaid inject its own "bomb" error graphic into the page
          // when a diagram is malformed — we handle failures ourselves below.
          suppressErrorRendering: true,
        });
        const id = `kriton-mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, sanitizeMermaid(code));
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    // If the model produced invalid Mermaid, fall back to showing the raw code
    // rather than a blank space.
    return (
      <pre className="my-4 overflow-x-auto rounded-xl border border-[#dfe8e5] bg-[#f7faf8] p-4 text-xs leading-5 text-[#31413e]">
        {code}
      </pre>
    );
  }

  return <div ref={ref} className="my-4 flex justify-center overflow-x-auto" />;
}

// Markdown element styling — tuned to match the existing answer look.
const mdComponents = {
  p: (props: ComponentPropsWithoutRef<"p">) => <p className="mb-3 last:mb-0" {...props} />,
  ul: (props: ComponentPropsWithoutRef<"ul">) => <ul className="mb-3 list-disc space-y-1 pl-5" {...props} />,
  ol: (props: ComponentPropsWithoutRef<"ol">) => <ol className="mb-3 list-decimal space-y-1 pl-5" {...props} />,
  strong: (props: ComponentPropsWithoutRef<"strong">) => <strong className="font-semibold text-[#17211f]" {...props} />,
  a: (props: ComponentPropsWithoutRef<"a">) => (
    <a className="text-[#16799a] underline" target="_blank" rel="noreferrer" {...props} />
  ),
  table: (props: ComponentPropsWithoutRef<"table">) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs" {...props} />
    </div>
  ),
  thead: (props: ComponentPropsWithoutRef<"thead">) => <thead className="bg-[#f1f7f8]" {...props} />,
  th: (props: ComponentPropsWithoutRef<"th">) => (
    <th className="border border-[#dfe8e5] px-3 py-2 font-semibold text-[#17211f]" {...props} />
  ),
  td: (props: ComponentPropsWithoutRef<"td">) => (
    <td className="border border-[#dfe8e5] px-3 py-2 align-top" {...props} />
  ),
  code: (props: ComponentPropsWithoutRef<"code">) => (
    <code className="rounded bg-[#f1f7f8] px-1 py-0.5 text-[12px]" {...props} />
  ),
  h1: (props: ComponentPropsWithoutRef<"h1">) => <h3 className="mb-2 mt-3 text-base font-bold text-[#17211f]" {...props} />,
  h2: (props: ComponentPropsWithoutRef<"h2">) => <h3 className="mb-2 mt-3 text-sm font-bold text-[#17211f]" {...props} />,
  h3: (props: ComponentPropsWithoutRef<"h3">) => <h4 className="mb-1 mt-2 text-sm font-semibold text-[#17211f]" {...props} />,
};

export function AnswerRenderer({ text, className }: { text: string; className?: string }) {
  const segments = parseSegments(text);
  return (
    <div className={`min-w-0 text-sm leading-7 text-[#31413e] ${className ?? ""}`}>
      {segments.map((seg, i) =>
        seg.type === "mermaid" ? (
          <MermaidDiagram key={i} code={seg.content} />
        ) : (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={mdComponents}>
            {stripInlineRefs(seg.content)}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}
