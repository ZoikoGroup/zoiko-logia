import type { SourceCitation } from "@/lib/api";

/** Backend title for a document excerpt: "<file name> — <location>". */
const DOCUMENT_TITLE = /^(.*?)\s+—\s+.+$/;

function isDocument(citation: SourceCitation): boolean {
  return citation.provider === "uploaded_document" || (!citation.url && DOCUMENT_TITLE.test(citation.title));
}

function fileName(citation: SourceCitation): string {
  return citation.title.match(DOCUMENT_TITLE)?.[1] ?? citation.title;
}

/**
 * Sources as a reader should see them: each source once.
 *
 * An uploaded file is cited once per excerpt the answer drew on ("ledger.csv —
 * 'ledger'!1:41", "ledger.csv — 'ledger'!42:81", …), so a long spreadsheet
 * filled the list with near-identical rows. Excerpts of one file collapse into
 * a single entry naming how many sections were used; any other source is
 * listed once per URL (or per title when it has none).
 *
 * Display only: the answer's citations, their ref ids and the audit trail are
 * unchanged, and inline reference markers are already hidden from the reader.
 */
export function uniqueCitations(citations: SourceCitation[]): SourceCitation[] {
  const groups = new Map<string, { citation: SourceCitation; sections: Set<string> }>();
  for (const citation of citations) {
    const document = isDocument(citation);
    const key = document
      ? `document:${citation.source_id || fileName(citation)}`
      : `source:${citation.url || citation.title}`;
    const group = groups.get(key);
    if (group) {
      group.sections.add(citation.title);
    } else {
      groups.set(key, { citation, sections: new Set([citation.title]) });
    }
  }
  return [...groups.values()].map(({ citation, sections }) => {
    if (!isDocument(citation)) return citation;
    const count = sections.size;
    return { ...citation, title: count > 1 ? `${fileName(citation)} — ${count} sections` : citation.title };
  });
}
