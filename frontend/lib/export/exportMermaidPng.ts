import { downloadBlob, sanitizeFilename } from "@/lib/visualizationExport";

/** Converts the already-rendered, strict-mode Mermaid SVG (see
 * WorkflowVisualization.tsx's MermaidGuide, which is the only source of the
 * `svg` string this ever receives) into a PNG via a plain canvas draw. This
 * never fetches or parses arbitrary external SVG — it only ever rasterizes
 * the one trusted string the caller already rendered. Resolves false on any
 * failure instead of throwing, so a broken diagram never crashes the
 * surrounding chat UI. */
export function exportMermaidPng(svg: string, title: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (!svg) {
      resolve(false);
      return;
    }
    const svgBlob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const image = new Image();

    const cleanup = () => URL.revokeObjectURL(url);

    image.onload = () => {
      // Some browsers throw SecurityError synchronously from canvas.toBlob()
      // for a "tainted" canvas (e.g. an SVG that still contains a
      // <foreignObject> somehow) rather than passing null to the callback —
      // a plain try/catch around the whole draw+export step is the only way
      // to catch that synchronous throw and degrade to a reported failure
      // instead of an uncaught exception reaching the surrounding chat UI.
      try {
        const scale = 2;
        const width = image.naturalWidth || 800;
        const height = image.naturalHeight || 600;
        const canvas = document.createElement("canvas");
        canvas.width = width * scale;
        canvas.height = height * scale;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          cleanup();
          resolve(false);
          return;
        }
        ctx.scale(scale, scale);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(image, 0, 0, width, height);
        cleanup();
        canvas.toBlob((blob) => {
          if (!blob) {
            resolve(false);
            return;
          }
          downloadBlob(blob, sanitizeFilename(title, "png"));
          resolve(true);
        }, "image/png");
      } catch {
        cleanup();
        resolve(false);
      }
    };
    image.onerror = () => {
      cleanup();
      resolve(false);
    };
    image.src = url;
  });
}
