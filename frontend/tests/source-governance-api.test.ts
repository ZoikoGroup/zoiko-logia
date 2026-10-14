import { afterEach, expect, it, vi } from "vitest";
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { signOut: vi.fn() } } }));
import { createSource, listSourceBundles } from "@/lib/api";
afterEach(() => vi.unstubAllGlobals());
it("sends explicitly chosen document permissions and terms without granting other rights", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "new-source" }) });
  vi.stubGlobal("fetch", fetcher);
  await createSource("token", { category: "tax", title: "Guidance", source_class: "authority", rights: { ingestion: true, indexing: true, retention: true }, terms_reference: "Licence 42" });
  const form = fetcher.mock.calls[0][1].body as FormData;
  expect(JSON.parse(form.get("rights_json") as string)).toEqual({ ingestion: true, indexing: true, retention: true });
  expect(form.get("terms_reference")).toBe("Licence 42");
});
it("loads persisted bundles through the source permission boundary", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
  vi.stubGlobal("fetch", fetcher);
  const signal = new AbortController().signal;
  await listSourceBundles("token", signal);
  expect(fetcher.mock.calls[0][0]).toMatch(/\/sources\/bundles$/);
  expect(fetcher.mock.calls[0][1].signal).toBe(signal);
});
