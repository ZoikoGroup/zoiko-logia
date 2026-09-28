/**
 * Normalize model and document text before Markdown/KaTeX parsing.
 *
 * U+202F is common in formatted financial values (for example `2 264`) but
 * KaTeX has no glyph metrics for it. Normalizing at the shared answer boundary
 * also fixes persisted answers created before this guard was added.
 */
export function sanitizeAnswerMarkdown(text: string): string {
  return text
    .replace(/\u202F/g, " ")
    .replace(/```(mermaid|chart)\s*[\s\S]*?```/g, "")
    .replace(/\n*\s*---\s*\n\s*⚠️\s*(?:\*\*)?Kriton™ Disclaimer(?:\*\*)?:[\s\S]*?latest effective standards\.\s*/gi, "")
    .replace(/\n*This response is for educational purposes only\. Consult a qualified professional\.\s*/gi, "")
    .replace(/^\s*(?:\*\*|__)?CLASSIF(?:ICATION|IED)(?:\*\*|__)?\s*:\s*[^\n]*\n?/gim, "")
    .replace(/^\s*(?:\*\*|__)?ANSWER(?:\*\*|__)?\s*:\s*/gim, "")
    .replace(/\*\*/g, "")
    .replace(/\s*\[\s*(?:REF-)?\d+(?:\s*,\s*(?:REF-)?\d+)*\s*\]/gi, "")
    .replace(/[ \t]+([.,;:])/g, "$1")
    .replace(/[ \t]{2,}/g, " ");
}

// In an accounting answer `$` overwhelmingly denotes currency. Allowing a
// single dollar delimiter makes a paragraph containing two monetary values
// become one accidental LaTeX expression. Display formulas (`$$...$$`) remain
// supported.
export const ANSWER_MATH_OPTIONS = { singleDollarTextMath: false } as const;

/** Only explicit multiline display-math fences are allowed to activate KaTeX. */
export function hasDisplayMath(text: string): boolean {
  return /(?:^|\n)[ \t]*\$\$[ \t]*\n[\s\S]*?\n[ \t]*\$\$(?=\n|$)/.test(text);
}
