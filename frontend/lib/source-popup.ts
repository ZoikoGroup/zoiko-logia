import type { SourceCitation } from "@/lib/api";

/**
 * Opens a small popup window for a citation instead of navigating the whole
 * tab away. Shows the genuine retrieved snippet (evidence_preview) when the
 * backend supplied one — never a fabricated excerpt.
 */
export function openSourcePopup(citation: SourceCitation): void {
  // No "noopener" in the feature string: passing it makes window.open()
  // return null by design, so the guard below always fired and the popup
  // was left blank. The rendered <a> carries rel="noopener noreferrer".
  const popup = window.open("", "_blank", "width=440,height=360");
  if (!popup) return;
  const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const safeTitle = escape(citation.title);
  popup.document.write(`
    <!doctype html>
    <html>
      <head>
        <title>${safeTitle}</title>
        <meta charset="utf-8" />
        <style>
          body { font: 14px/1.5 -apple-system, system-ui, sans-serif; padding: 20px; color: #17211f; }
          h1 { font-size: 15px; margin: 0 0 6px; }
          p { color: #667673; font-size: 12px; margin: 0 0 16px; }
          blockquote { margin: 0 0 16px; padding: 10px 12px; background: #f7faf8; border-left: 3px solid #16799a; border-radius: 4px; font-size: 13px; color: #31413e; }
          a { color: #16799a; font-weight: 600; text-decoration: none; }
        </style>
      </head>
      <body>
        <h1>${safeTitle}</h1>
        <p>Reference ${citation.ref_id}</p>
        ${citation.evidence_preview ? `<blockquote>${escape(citation.evidence_preview)}${citation.evidence_preview.length >= 240 ? "…" : ""}</blockquote>` : ""}
        ${citation.url ? `<a href="${citation.url}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : "<p>No external link available for this source.</p>"}
      </body>
    </html>
  `);
  popup.document.close();
}
