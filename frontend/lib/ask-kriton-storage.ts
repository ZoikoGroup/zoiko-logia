import type { AskKritonResponse } from "@/lib/api";

/** A document that was attached to one question. Recorded per turn, not per
 *  conversation: the composer is cleared once a question is sent, so each turn
 *  is a faithful record of what that particular answer could see. Persisted
 *  with the conversation so scrolling back still shows which file an answer
 *  was grounded in. */
export type TurnAttachment = {
  documentId: string;
  name: string;
  chunkCount?: number;
};

export type Turn = {
  id: string;
  /** Raw text as typed, before any quick-mode prefix or follow-up context tail. */
  query: string;
  /** Exact text actually sent to the backend for this turn. */
  submittedQuery: string;
  loading: boolean;
  error: string | null;
  /** HTTP status behind `error`, when the failure came from the API. Lets the
   *  UI distinguish "Kriton answered with a 4xx/5xx" from "the request never
   *  reached Kriton" instead of showing one generic message for both. */
  errorStatus?: number | null;
  /** The failed request's id (its Idempotency-Key), as logged in backend/logs/kriton-requests.log. */
  errorRequestId?: string;
  result: AskKritonResponse | null;
  /** Latest server-reported orchestration stage while this turn is running. */
  progressMessage?: string;
  /** Documents sent with this question. Optional so conversations stored
   *  before this existed still load. */
  attachments?: TurnAttachment[];
};

export type Conversation = {
  id: string;
  title: string;
  turns: Turn[];
  createdAt: number;
  updatedAt: number;
  pinned: boolean;
  documentIds?: string[];
  /** The project (engagement) this chat belongs to; absent for "No project". */
  engagementId?: string;
};

const CONVERSATIONS_KEY = "kriton_conversations_v3";
const LEGACY_CONVERSATIONS_KEY = "kriton_conversations";
export const MAX_CONVERSATIONS = 30;
/** The open chat lives in the URL (?chat=<id>), not in storage. */
export const CHAT_PARAM = "chat";

type LegacyTurn = { id: string; question: string; result: AskKritonResponse | null; error: string | null; loading: boolean };
type LegacyConversation = { id: string; title: string; turns: LegacyTurn[]; createdAt: number };

function isLegacyTurn(t: unknown): t is LegacyTurn {
  return !!t && typeof t === "object" && "question" in t;
}

/** Best-effort migration from the older, simpler storage schema (turns keyed
 * by `question` instead of `query`/`submittedQuery`, no pin/updatedAt). */
function migrateLegacy(raw: unknown): Conversation[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((c: LegacyConversation) => ({
    id: c.id,
    title: c.title,
    createdAt: c.createdAt,
    updatedAt: c.createdAt,
    pinned: false,
    documentIds: [],
    turns: (c.turns ?? []).map((t) =>
      isLegacyTurn(t)
        ? { id: t.id, query: t.question, submittedQuery: t.question, loading: t.loading, error: t.error, result: t.result }
        : (t as unknown as Turn),
    ),
  }));
}

/** A turn still marked `loading: true` on load was mid-flight when the page
 * closed/refreshed — the in-flight promise is gone, so it can never resolve.
 * Recover it as an explicit interrupted error rather than a stuck spinner. */
function recoverInterruptedTurns(conversations: Conversation[]): Conversation[] {
  return conversations.map((c) => ({
    ...c,
    turns: c.turns.map((t) =>
      t.loading ? { ...t, loading: false, error: "This request was interrupted — please ask again.", result: null } : t,
    ),
  }));
}

export function loadConversations(): Conversation[] {
  try {
    const current = localStorage.getItem(CONVERSATIONS_KEY);
    if (current) {
      const parsed = JSON.parse(current);
      if (Array.isArray(parsed)) return recoverInterruptedTurns(parsed);
    }
    const legacy = localStorage.getItem(LEGACY_CONVERSATIONS_KEY);
    if (legacy) {
      const migrated = recoverInterruptedTurns(migrateLegacy(JSON.parse(legacy)));
      if (migrated.length > 0) persistConversations(migrated);
      return migrated;
    }
  } catch {
    /* ignore malformed storage */
  }
  return [];
}

/** How many chats to try keeping when storage is full, most recent first. */
const FALLBACK_COUNTS = [20, 12, 8, 5, 3, 2, 1];

// ── Full copy in IndexedDB ──────────────────────────────────────────────────
// localStorage holds about 5 MB, so long chats were cut to their first question
// or dropped (19 Nov 2026). IndexedDB holds far more: every chat and every
// question and answer is kept there; localStorage stays as the instant copy
// the page opens with, replaced by the full copy a moment later.
const IDB_NAME = "kriton";
const IDB_STORE = "conversations";
const IDB_KEY = "all";
/** Chats kept in the full copy, most recently used first. */
export const MAX_STORED_CONVERSATIONS = 200;

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const request = indexedDB.open(IDB_NAME, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(IDB_STORE);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

function saveFullCopy(conversations: Conversation[]): void {
  void openDb().then((db) => {
    if (!db) return;
    try {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).put(conversations.slice(0, MAX_STORED_CONVERSATIONS), IDB_KEY);
      tx.oncomplete = () => db.close();
      tx.onerror = () => db.close();
    } catch {
      db.close();
    }
  });
}

/** Every stored chat in full, or null when IndexedDB is unavailable or empty. */
export async function loadFullConversations(): Promise<Conversation[] | null> {
  const db = await openDb();
  if (!db) return null;
  return new Promise((resolve) => {
    try {
      const request = db.transaction(IDB_STORE, "readonly").objectStore(IDB_STORE).get(IDB_KEY);
      request.onsuccess = () => {
        db.close();
        resolve(Array.isArray(request.result) ? recoverInterruptedTurns(request.result) : null);
      };
      request.onerror = () => {
        db.close();
        resolve(null);
      };
    } catch {
      db.close();
      resolve(null);
    }
  });
}

/** Both copies of the chats as one: for each chat the more recent version,
 * and on a tie the one with more questions, so nothing asked is lost. */
export function mergeConversations(shown: Conversation[], stored: Conversation[]): Conversation[] {
  const byId = new Map<string, Conversation>();
  for (const conversation of [...stored, ...shown]) {
    const other = byId.get(conversation.id);
    if (!other || conversation.updatedAt > other.updatedAt
        || (conversation.updatedAt === other.updatedAt && conversation.turns.length > other.turns.length)) {
      byId.set(conversation.id, conversation);
    }
  }
  return [...byId.values()].sort((a, b) => b.updatedAt - a.updatedAt);
}

/**
 * Save the chats. Browser storage holds about 5 MB; a full write used to fail
 * silently, so the stored copy stayed at an old state — a ten-question chat
 * reopened with only its first question (19 Nov 2026). When storage is full,
 * the most recently used chats are kept and the oldest dropped, so the chat
 * being worked on is always saved in full.
 */
export function persistConversations(conversations: Conversation[]): void {
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);
  saveFullCopy(sorted);
  const recentFirst = sorted.slice(0, MAX_CONVERSATIONS);
  for (const count of [recentFirst.length, ...FALLBACK_COUNTS.filter((n) => n < recentFirst.length)]) {
    try {
      localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(recentFirst.slice(0, count)));
      return;
    } catch {
      /* storage full (or unavailable): try again with fewer, older chats dropped */
    }
  }
}

/** The chat a page load shows: the one named in the URL, so a reload keeps
 * it. A plain /ask-kriton (the dashboard, sidebar and page links) starts a new
 * chat; reading the last chat from storage reopened it on every visit. */
export function chatIdFromUrl(search: string, conversations: Conversation[]): string | null {
  const id = new URLSearchParams(search).get(CHAT_PARAM);
  return id && conversations.some((conversation) => conversation.id === id) ? id : null;
}

/** The current address with ?chat=<id> set, or removed for a new chat. */
export function chatUrl(currentHref: string, id: string | null): string {
  const url = new URL(currentHref);
  if (id) url.searchParams.set(CHAT_PARAM, id);
  else url.searchParams.delete(CHAT_PARAM);
  return url.pathname + url.search + url.hash;
}

/** Pinned first, then most-recently-updated. */
export function sortConversations(conversations: Conversation[]): Conversation[] {
  return [...conversations].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return b.updatedAt - a.updatedAt;
  });
}
