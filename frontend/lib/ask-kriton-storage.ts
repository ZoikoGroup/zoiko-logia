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

export function persistConversations(conversations: Conversation[]): void {
  try {
    localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS)));
  } catch {
    /* ignore storage write failures (e.g. private mode / quota) */
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
