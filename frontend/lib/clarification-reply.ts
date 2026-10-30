import type { AskKritonResponse } from "@/lib/api";

type TurnLike = {
  submittedQuery: string;
  result: (Pick<AskKritonResponse, "outcome" | "query_id"> & { next_action?: { message?: string } | null }) | null;
};

export type OpenClarification = {
  /** The query_id of Kriton's latest question: sent as reply_to. */
  replyTo: string;
  /** The request being clarified, with the earlier replies that answered something: sent as previous_query. */
  request: string;
  /** How many questions Kriton has asked in a row (clarification_cycle). */
  cycle: number;
};

// Backend limit (AskKritonRequest.previous_query): longer text is rejected.
const PREVIOUS_QUERY_CHARS = 4000;

/** The question Kriton is waiting on, if its latest turn asked one. An
 * acknowledgement ("Noted — …", outcome "acknowledged") asks nothing, so
 * the next message after it is a new one, never a reply (backend stage 2:
 * explicit message types instead of inferring replies from wording).
 *
 * A reply after which Kriton asked exactly the same question answered
 * nothing, so it is not carried: '"in advance or in arrears?"' sent as a
 * reply named both timings, and every later reply ("In arrears.") was read
 * with it and asked again, without end (28 Oct 2026). */
export function openClarification(turns: TurnLike[]): OpenClarification | null {
  const exchange: TurnLike[] = [];
  for (let i = turns.length - 1; i >= 0 && turns[i].result?.outcome === "clarification_required"; i--) {
    exchange.unshift(turns[i]);
  }
  const replyTo = turns.at(-1)?.result?.query_id;
  if (!exchange.length || !replyTo) return null;
  const question = (turn: TurnLike) => turn.result?.next_action?.message?.trim() ?? "";
  const carried = exchange.filter((turn, index) => index === 0 || question(turn) !== question(exchange[index - 1]));
  return {
    replyTo,
    request: carried.map((turn) => turn.submittedQuery.trim()).join("\n").slice(0, PREVIOUS_QUERY_CHARS),
    cycle: exchange.length,
  };
}
