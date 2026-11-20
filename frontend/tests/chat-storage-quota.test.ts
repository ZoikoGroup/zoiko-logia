import { afterEach, describe, expect, it, vi } from "vitest";
import { loadConversations, mergeConversations, persistConversations, type Conversation } from "@/lib/ask-kriton-storage";

// 19 Nov 2026: a ten-question chat reopened with only its first question —
// storage was full, the save failed silently and the old copy stayed.
function chat(id: string, updatedAt: number, turns: number, size = 10): Conversation {
  return {
    id, title: id, createdAt: 0, updatedAt, pinned: false,
    turns: Array.from({ length: turns }, (_, i) => ({
      id: `${id}-${i}`, query: `q${i}`, submittedQuery: `q${i}`, loading: false, error: null,
      result: { answer: { text: "x".repeat(size) } } as never,
    })),
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("saving chats when browser storage is full", () => {
  it("keeps the most recent chat with all its questions", () => {
    const store = new Map<string, string>();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation((key: string, value: string) => {
      if (value.length > 60_000) throw new DOMException("quota", "QuotaExceededError");
      store.set(key, value);
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation((key: string) => store.get(key) ?? null);
    const old = Array.from({ length: 10 }, (_, i) => chat(`old-${i}`, i, 3, 2_000));
    const current = chat("current", 100, 10, 2_000);

    persistConversations([...old, current]);

    const saved = loadConversations();
    const reopened = saved.find((c) => c.id === "current");
    expect(reopened?.turns).toHaveLength(10);
    expect(saved.length).toBeLessThan(11);           // older chats dropped to fit
  });

  it("keeps every question when the full copy and the quick copy differ", () => {
    // The full copy (IndexedDB) has the whole chat; the quick copy only its
    // first question, and a newer chat asked meanwhile is kept too.
    const full = [chat("long", 50, 10), chat("other", 10, 3)];
    const quick = [chat("long", 50, 1), chat("new", 60, 1)];
    const merged = mergeConversations(quick, full);
    expect(merged.map((c) => [c.id, c.turns.length])).toEqual([["new", 1], ["long", 10], ["other", 3]]);
  });

  it("saves everything when there is room", () => {
    persistConversations([chat("a", 1, 2), chat("b", 2, 10)]);
    expect(loadConversations().map((c) => [c.id, c.turns.length])).toEqual([["b", 10], ["a", 2]]);
  });
});
