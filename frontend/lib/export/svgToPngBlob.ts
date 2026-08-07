/** Rasterizes an already-rendered, trusted SVG string to a PNG Blob.
 *
 * Extracted from exportMermaidPng so that "Download PNG" and "Copy image"
 * share one rasterization path — a second implementation would eventually
 * disagree with the first about scale, background or tainting, and a copied
 * figure that does not match the downloaded one is a governance problem, not
 * just a cosmetic one.
 *
 * Never fetches or parses arbitrary external SVG: it only ever rasterizes the
 * one trusted string the caller already rendered. Resolves null on any
 * failure instead of throwing, so a broken diagram cannot crash the
 * surrounding chat UI. */
export function svgToPngBlob(svg: string): Promise<Blob | null> {
  return new Promise((resolve) => {
    if (!svg) {
      resolve(null);
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
          resolve(null);
          return;
        }
        ctx.scale(scale, scale);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(image, 0, 0, width, height);
        cleanup();
        canvas.toBlob((blob) => resolve(blob), "image/png");
      } catch {
        cleanup();
        resolve(null);
      }
    };
    image.onerror = () => {
      cleanup();
      resolve(null);
    };
    image.src = url;
  });
}

/** The SVG of a live Recharts/Plotly container, serialized for rasterization.
 * Returns null when the container has not rendered an <svg> yet. */
export function serializeContainerSvg(container: HTMLElement | null): string | null {
  const svg = container?.querySelector("svg");
  if (!svg) return null;
  const clone = svg.cloneNode(true) as SVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  return new XMLSerializer().serializeToString(clone);
}
