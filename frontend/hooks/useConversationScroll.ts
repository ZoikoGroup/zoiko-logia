"use client";

import { useCallback, useEffect, useRef } from "react";

/** Keep older messages in view when a reply completes while the user reads up-thread. */
export function useConversationScroll(conversationId: string | null, turnCount: number, loading: boolean) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const followingLatest = useRef(true);
  const previous = useRef({ conversationId, turnCount });
  const onScroll = useCallback(() => {
    const box = scrollRef.current;
    if (box) followingLatest.current = box.scrollHeight - box.clientHeight - box.scrollTop <= 80;
  }, []);

  useEffect(() => {
    const changed = previous.current.conversationId !== conversationId || previous.current.turnCount !== turnCount;
    previous.current = { conversationId, turnCount };
    const box = scrollRef.current;
    if (box && (changed || followingLatest.current)) {
      followingLatest.current = true;
      box.scrollTo({ top: box.scrollHeight, behavior: changed ? "instant" : "smooth" });
    }
  }, [conversationId, turnCount, loading]);

  return { scrollRef, onScroll };
}
