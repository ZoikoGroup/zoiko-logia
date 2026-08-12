/**
 * Clipboard, download and tabular-export helpers shared by the answer surface.
 *
 * These live outside the components so the chart toolbar, the markdown-table
 * toolbar and the response actions all export the same way — a figure copied
 * from a chart and the same figure copied from its "View as table" view should
 * never disagree about formatting.
 */

/** Marker that `build_validated_disclaimer` (backend composition_validator.py)
 * appends to an answer. The disclaimer is fixed boilerplate the app adds, not
 * model output, so "copy the response" should not include it. */
const DISCLAIMER_MARKER = "Kriton™ Disclaimer";

/** Inline citation markers are internal ref ids, meaningless outside the app. */
const REF_MARKER = /\s*\[\s*(?:REF-)?\d+(?:\s*,\s*(?:REF-)?\d+)*\s*\]/gi;

/**
 * The answer body alone — what the user actually asked Kriton, with the
 * appended disclaimer and any inline citation markers removed.
 *
 * The disclaimer is cut at the `---` rule that precedes it rather than at the
 * marker itself, so the separator does not survive as a dangling horizontal
 * rule at the end of the copied text.
 */
export function answerBodyOnly(text: string): string {
  let body = text;
  const markerAt = body.indexOf(DISCLAIMER_MARKER);
  if (markerAt !== -1) {
    const ruleAt = body.lastIndexOf("\n---", markerAt);
    body = body.slice(0, ruleAt === -1 ? markerAt : ruleAt);
  }
  return body.replace(REF_MARKER, "").replace(/[ \t]+\n/g, "\n").trim();
}

export async function writeTextToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  // navigator.clipboard is undefined outside secure contexts (plain http on a
  // LAN IP, for instance), so fall back to the legacy selection-based copy.
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("Clipboard copy was rejected");
}

/** Writes a rendered figure to the clipboard as a real image, so it pastes into
 * Word/Slides/Teams as a picture rather than as a file path. No execCommand
 * fallback: legacy browsers cannot put binary data on the clipboard at all, and
 * silently copying nothing is worse than a reported failure — so this throws
 * and the caller surfaces it. */
export async function writeImageToClipboard(blob: Blob) {
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("This browser cannot copy images to the clipboard");
  }
  await navigator.clipboard.write([new ClipboardItem({ [blob.type || "image/png"]: blob })]);
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function downloadTextFile(contents: string, filename: string, mime = "text/markdown;charset=utf-8") {
  downloadBlob(new Blob([contents], { type: mime }), filename);
}

export function safeDownloadName(value: string, extension: string) {
  const stem =
    value
      .normalize("NFKD")
      .replace(/[^a-zA-Z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase()
      .slice(0, 80) || "kriton-answer";
  return `${stem}.${extension}`;
}

/** TSV rather than CSV: TSV is what spreadsheets accept straight off the
 * clipboard, splitting into cells without an import dialog. */
export function tableRowsToTsv(rows: readonly (readonly string[])[]) {
  return rows.map((row) => row.map((cell) => cell.replace(/\s+/g, " ").trim()).join("\t")).join("\n");
}

export function tableRowsToMarkdown(rows: readonly (readonly string[])[]) {
  if (!rows.length) return "";
  const clean = (cell: string) => cell.replace(/\s+/g, " ").replace(/\|/g, "\\|").trim();
  const [header, ...body] = rows;
  return [
    `| ${header.map(clean).join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...body.map((row) => `| ${row.map(clean).join(" | ")} |`),
  ].join("\n");
}

/** Reads a rendered <table> back out of the DOM. The rendered table IS the
 * source here, so every column comes across exactly as displayed — including
 * anything the markdown renderer reformatted. */
export function tableElementToRows(table: HTMLTableElement): string[][] {
  return Array.from(table.rows).map((row) =>
    Array.from(row.cells).map((cell) => cell.innerText ?? cell.textContent ?? ""),
  );
}

/** Rasterizes an <svg> (a Mermaid diagram) to a PNG blob at 2x for a crisp
 * paste. The SVG is inlined as a data URL first because a blob: URL taints the
 * canvas in some browsers, which would make toBlob() throw on export. */
export async function svgElementToPngBlob(svg: SVGSVGElement, scale = 2): Promise<Blob> {
  const box = svg.getBoundingClientRect();
  const width = Math.max(1, Math.ceil(box.width || svg.viewBox.baseVal.width || 800));
  const height = Math.max(1, Math.ceil(box.height || svg.viewBox.baseVal.height || 600));

  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const source = new XMLSerializer().serializeToString(clone);
  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;

  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Could not rasterize the diagram"));
    img.src = dataUrl;
  });

  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is unavailable");
  // Mermaid SVGs are transparent; a white ground keeps them readable when
  // pasted onto a dark slide.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not encode the image"))), "image/png");
  });
}

/** Copies a live <canvas> (an ECharts chart) onto an opaque ground and encodes
 * it as PNG. ECharts renders on a transparent canvas, and a transparent PNG
 * pasted onto a dark slide loses its axis labels entirely — so the background
 * is painted explicitly rather than inherited. */
export async function canvasElementToPngBlob(
  canvas: HTMLCanvasElement,
  background = "#ffffff",
): Promise<Blob> {
  const out = document.createElement("canvas");
  out.width = canvas.width;
  out.height = canvas.height;
  const ctx = out.getContext("2d");
  if (!ctx) throw new Error("Canvas is unavailable");
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(canvas, 0, 0);

  return await new Promise<Blob>((resolve, reject) => {
    out.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not encode the image"))), "image/png");
  });
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  return await (await fetch(dataUrl)).blob();
}
