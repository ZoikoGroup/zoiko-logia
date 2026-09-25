/**
 * The model writes display maths as \[ … \] and inline maths as \( … \), but
 * remark-math only recognises $$ … $$ and $ … $ — and Markdown reads "\[" as
 * an escaped "[" — so formulas reached the reader as "[ \text{COGS} = … ]".
 * Rewrite the delimiters outside code spans/blocks, which stay untouched.
 */
export function normaliseLatexDelimiters(text: string): string {
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part
            .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body: string) => `\n$$\n${body.trim()}\n$$\n`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body: string) => `$${body.trim()}$`),
    )
    .join("");
}
