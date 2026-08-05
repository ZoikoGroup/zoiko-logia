import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { exportMermaidPng } from "@/lib/export/exportMermaidPng";

class FakeImage {
  static instances: FakeImage[] = [];
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  naturalWidth = 400;
  naturalHeight = 200;
  private _src = "";
  set src(value: string) {
    this._src = value;
    FakeImage.instances.push(this);
  }
  get src() {
    return this._src;
  }
}

describe("exportMermaidPng", () => {
  let originalImage: typeof Image;
  let originalCreateElement: typeof document.createElement;
  let toBlobSucceeds = true;
  let toBlobThrowsTaintedCanvasError = false;

  beforeEach(() => {
    FakeImage.instances = [];
    toBlobSucceeds = true;
    toBlobThrowsTaintedCanvasError = false;
    originalImage = global.Image;
    // @ts-expect-error — test double stands in for the real Image constructor
    global.Image = FakeImage;

    originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
      if (tag === "canvas") {
        return {
          width: 0,
          height: 0,
          getContext: () => ({ scale: vi.fn(), fillStyle: "", fillRect: vi.fn(), drawImage: vi.fn() }),
          toBlob: (callback: (blob: Blob | null) => void) => {
            if (toBlobThrowsTaintedCanvasError) {
              // Reproduces the live bug: some browsers throw SecurityError
              // synchronously from toBlob() for a tainted canvas rather than
              // invoking the callback with null.
              throw new DOMException("Tainted canvases may not be exported.", "SecurityError");
            }
            callback(toBlobSucceeds ? new Blob(["png-bytes"], { type: "image/png" }) : null);
          },
        } as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tag);
    }) as typeof document.createElement);

    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    global.Image = originalImage;
    vi.restoreAllMocks();
  });

  it("converts a valid strict-mode Mermaid SVG into a downloaded PNG", async () => {
    const promise = exportMermaidPng("<svg>diagram</svg>", "Sequence flow");
    expect(FakeImage.instances).toHaveLength(1);
    FakeImage.instances[0].onload?.();
    await expect(promise).resolves.toBe(true);
  });

  it("reports a conversion failure safely instead of throwing when the image fails to decode", async () => {
    const promise = exportMermaidPng("<svg>broken</svg>", "Sequence flow");
    FakeImage.instances[0].onerror?.();
    await expect(promise).resolves.toBe(false);
  });

  it("reports failure safely when canvas.toBlob cannot produce a PNG", async () => {
    toBlobSucceeds = false;
    const promise = exportMermaidPng("<svg>diagram</svg>", "Sequence flow");
    FakeImage.instances[0].onload?.();
    await expect(promise).resolves.toBe(false);
  });

  it("reports failure safely when the canvas is tainted (SecurityError thrown synchronously by toBlob)", async () => {
    toBlobThrowsTaintedCanvasError = true;
    const promise = exportMermaidPng("<svg>diagram</svg>", "Sequence flow");
    FakeImage.instances[0].onload?.();
    await expect(promise).resolves.toBe(false);
  });

  it("resolves false immediately for an empty SVG without touching the DOM", async () => {
    await expect(exportMermaidPng("", "title")).resolves.toBe(false);
    expect(FakeImage.instances).toHaveLength(0);
  });
});
