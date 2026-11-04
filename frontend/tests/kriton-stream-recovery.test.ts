import { afterEach, describe, expect, it, vi } from "vitest";
import { askKriton, askKritonStream } from "@/lib/api";
import { fetchWithSession } from "@/lib/auth-fetch";
import { syntheticKritonResponse } from "./fixtures/kriton-response";

vi.mock("@/lib/auth-fetch", () => ({ fetchWithSession: vi.fn() }));
const fetchMock = vi.mocked(fetchWithSession);
const data = syntheticKritonResponse();
const frame = JSON.stringify({ type: "result", data });
const ask = (progress = vi.fn()) => askKritonStream("synthetic-token", { query: "Calculate 2 + 2" }, "synthetic-key", progress);
function respond(chunks: string[]) {
  fetchMock.mockResolvedValue(new Response(new ReadableStream<Uint8Array>({
    start(controller) { for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk)); controller.close(); },
  }), { headers: { "Content-Type": "application/x-ndjson" } }));
}
afterEach(() => { vi.clearAllMocks(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("Kriton terminal stream frames", () => {
  it.each(["", "\n", "\r\n"])("accepts a complete final result with ending %j", async (ending) => {
    respond([frame + ending]);
    expect(await ask()).toEqual(data);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/orchestration\/ask\/stream$/);
  });
  it("preserves progress and a result split across transport chunks", async () => {
    const progress = vi.fn();
    respond(['{"type":"progress","stage":"retrieving","message":"Checking evidence"}\n', frame.slice(0, 9), frame.slice(9)]);
    expect(await ask(progress)).toEqual(data);
    expect(progress).toHaveBeenCalledWith({ stage: "retrieving", message: "Checking evidence" });
  });
  it.each([undefined, null, {}, { query_id: "x" }, { query_id: "x", outcome: "invented" }])("rejects an unusable terminal payload %j", async (invalid) => {
    respond([JSON.stringify({ type: "result", data: invalid }) + "\n"]);
    await expect(ask()).rejects.toMatchObject({ status: 502 });
  });
  it("reports malformed wire data as a recoverable protocol failure", async () => {
    respond(['{"type":"result",oops}\n']);
    await expect(ask()).rejects.toMatchObject({ status: 502 });
  });
  it("does not mistake progress-only disconnect for completion", async () => {
    respond(['{"type":"heartbeat"}\n']);
    await expect(ask()).rejects.toMatchObject({ status: 502 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("preserves an explicit terminal error without a final newline", async () => {
    respond([JSON.stringify({ type: "error", status: 504, message: "Request timed out. Retry with the request ID." })]);
    await expect(ask()).rejects.toMatchObject({ status: 504, message: "Request timed out. Retry with the request ID." });
  });
  it("cancels and unlocks the transport after an early result", async () => {
    const cancelled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode(frame + "\n")); }, cancel: cancelled });
    fetchMock.mockResolvedValue(new Response(body));
    expect(await ask()).toEqual(data);
    expect(cancelled).toHaveBeenCalledTimes(1);
    expect(body.locked).toBe(false);
  });
});

it("preserves split UTF-8 characters across network chunks", async () => {
  const unicodeData = { ...data, answer: { ...data.answer!, text: "VAT £833.33" } };
  const bytes = new TextEncoder().encode(JSON.stringify({ type: "result", data: unicodeData }));
  const split = bytes.indexOf(0xc2) + 1;
  const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes.slice(0, split)); controller.enqueue(bytes.slice(split)); controller.close(); } });
  fetchMock.mockResolvedValue(new Response(body));
  expect(await ask()).toEqual(unicodeData);
});

it("reports an interrupted reader as a connection failure without resubmitting", async () => {
  const body = new ReadableStream<Uint8Array>({ start(controller) { controller.error(new TypeError("synthetic disconnect")); } });
  fetchMock.mockResolvedValue(new Response(body));
  await expect(ask()).rejects.toMatchObject({ status: 0 });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("times out a silent connection without automatic duplicate submissions", async () => {
  vi.useFakeTimers();
  fetchMock.mockImplementation(async (_url, _token, init) => new Response(new ReadableStream<Uint8Array>({
    start(controller) { init?.signal?.addEventListener("abort", () => controller.error(new DOMException("synthetic abort", "AbortError"))); },
  })));
  const rejection = expect(ask()).rejects.toMatchObject({ status: 408 });
  await vi.advanceTimersByTimeAsync(120_001);
  await rejection;
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("keeps a live heartbeat connection open beyond two minutes", async () => {
  vi.useFakeTimers();
  let stream: ReadableStreamDefaultController<Uint8Array>;
  fetchMock.mockImplementation(async (_url, _token, init) => new Response(new ReadableStream<Uint8Array>({
    start(controller) { stream = controller; init?.signal?.addEventListener("abort", () => controller.error(new DOMException("synthetic abort", "AbortError"))); },
  })));
  const pending = ask();
  const result = expect(pending).resolves.toEqual(data);
  for (let index = 0; index < 3; index++) {
    await vi.advanceTimersByTimeAsync(90_000);
    stream!.enqueue(new TextEncoder().encode('{"type":"heartbeat"}\n'));
    await vi.advanceTimersByTimeAsync(0);
  }
  stream!.enqueue(new TextEncoder().encode(frame));
  stream!.close();
  await result;
  expect(fetchMock).toHaveBeenCalledTimes(1);
});


it("classifies its own non-stream timeout even for DOMException objects", async () => {
  vi.useFakeTimers();
  fetchMock.mockImplementation(async (_url, _token, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("synthetic abort", "AbortError")));
  }));
  const rejection = expect(askKriton("synthetic-token", { query: "Calculate 2 + 2" }, "synthetic-key")).rejects.toMatchObject({ status: 408 });
  await vi.advanceTimersByTimeAsync(120_001);
  await rejection;
  expect(fetchMock).toHaveBeenCalledTimes(1);
});


it.each([
  { query_id: "x", outcome: "answered" },
  { ...data, answer: { text: "4", citations: null, limitations: [] } },
  { ...data, answer: { text: null, citations: [], limitations: [] } },
  { ...data, safety: null },
  { ...data, artifacts: null },
])("rejects a superficially identified response that cannot be rendered", async (invalid) => {
  respond([JSON.stringify({ type: "result", data: invalid }) + "\n"]);
  await expect(ask()).rejects.toMatchObject({ status: 502 });
});

it.each(["unavailable", "refused", "clarification_required", "escalated", "limited_response", "rejected"] as const)("preserves a valid %s outcome without converting it to answered", async (outcome) => {
  const expected = syntheticKritonResponse({ outcome, answer: null, next_action: { type: "explicit_action", message: "Cannot supply a factual answer." } });
  respond([JSON.stringify({ type: "result", data: expected }) + "\n"]);
  expect(await ask()).toEqual(expected);
});

it("applies the same response checks to non-stream replies", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ ...data, answer: { text: "4", citations: null } })));
  await expect(askKriton("synthetic-token", { query: "Calculate 2 + 2" })).rejects.toMatchObject({ status: 502 });
});

it("reports malformed non-stream JSON as an explicit response error", async () => {
  fetchMock.mockResolvedValue(new Response("{broken-json"));
  await expect(askKriton("synthetic-token", { query: "Calculate 2 + 2" })).rejects.toMatchObject({ status: 502 });
});


it("reports cleanup failure safely without masking a valid terminal result", async () => {
  const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new TextEncoder().encode(frame + "\n")); },
    cancel() { return Promise.reject(new Error("synthetic-sensitive-body-must-not-be-logged")); },
  });
  fetchMock.mockResolvedValue(new Response(body));
  expect(await ask()).toEqual(data);
  await vi.waitFor(() => expect(warning).toHaveBeenCalledWith("Kriton stream cleanup failed.", { event: "kriton_stream_cleanup_failed", request_id: "synthetic-key" }));
  expect(JSON.stringify(warning.mock.calls)).not.toContain("synthetic-sensitive-body");
  expect(body.locked).toBe(false);
});

function scopedVerification(over: Record<string, unknown> = {}) {
  return { arithmetic: "verified", sources: "not_applicable", assumptions: "confirmed", overall: "fully_verified", ...over };
}
const inconsistentReplies = [
  ...[false, 0, ""].map((verification) => ({ ...data, answer: { ...data.answer!, verification } })),
  { ...data, answer: { ...data.answer!, verification: scopedVerification({ arithmetic: "mismatch" }) } },
  { ...data, answer: { ...data.answer!, verification: scopedVerification({ sources: "unsupported" }) } },
  { ...data, answer: { ...data.answer!, verification: scopedVerification({ assumptions: "stated" }) } },
  { ...data, answer: { ...data.answer!, verification: scopedVerification({ arithmetic: "invented_status" }) } },
  { ...data, answer: { ...data.answer!, completeness: "partial", verification: scopedVerification() } },
  { ...data, safety: { ...data.safety, policy_state: "blocked" } },
  { ...data, answer: { ...data.answer!, text: "A claim [REF-99].", citations: [{ ref_id: "REF-1", source_id: "s1", title: "Synthetic", url: null }] } },
];
it.each(inconsistentReplies)("rejects inconsistent verification/policy/citation metadata in both request paths", async (invalid) => {
  respond([JSON.stringify({ type: "result", data: invalid }) + "\n"]);
  await expect(ask()).rejects.toMatchObject({ status: 502 });
  fetchMock.mockResolvedValue(new Response(JSON.stringify(invalid)));
  await expect(askKriton("synthetic-token", { query: "Synthetic check" })).rejects.toMatchObject({ status: 502 });
});

it("keeps a legitimate partial response unchanged", async () => {
  const partial = { ...data, answer: { ...data.answer!, completeness: "partial", verification: scopedVerification({ overall: "partially_verified", assumptions: "stated" }) } };
  respond([JSON.stringify({ type: "result", data: partial }) + "\n"]);
  expect(await ask()).toEqual(partial);
});

it("preserves supported grouped references and uncited document provenance", async () => {
  const supported = { ...data, answer: { ...data.answer!, text: "Synthetic support [REF-1, REF-2].", citations: [1, 2, 3].map((n) => ({ ref_id: `REF-${n}`, source_id: `s${n}`, title: "Synthetic", url: null })) } };
  respond([JSON.stringify({ type: "result", data: supported }) + "\n"]);
  expect(await ask()).toEqual(supported);
});
