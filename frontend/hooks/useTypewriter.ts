"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Progressively reveals `text` word-by-word rather than rendering it all at
 * once. Purely a client-side rendering effect — the backend still returns
 * the complete, already-validated answer in one response (Checkpoint C
 * validates the full text before it's ever sent); this never streams
 * partial/unvalidated model output, it just animates the reveal of text
 * that has already fully arrived.
 *
 * Word-by-word (not char-by-char) reads more naturally and is cheaper on
 * re-renders. Skips straight to the full text when the user prefers
 * reduced motion, matching the reduced-motion handling already applied to
 * this page's other animations (globals.css).
 */
export function useTypewriter(text: string, wordsPerTick = 2, tickMs = 28): string {
  const [visibleWordCount, setVisibleWordCount] = useState(0);
  const wordsRef = useRef<string[]>([]);

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    wordsRef.current = text.split(/(\s+)/); // keep whitespace tokens so spacing is preserved exactly
    if (prefersReducedMotion || wordsRef.current.length === 0) {
      setVisibleWordCount(wordsRef.current.length);
      return;
    }

    setVisibleWordCount(0);
    const interval = setInterval(() => {
      setVisibleWordCount((count) => {
        const next = count + wordsPerTick;
        if (next >= wordsRef.current.length) {
          clearInterval(interval);
          return wordsRef.current.length;
        }
        return next;
      });
    }, tickMs);

    return () => clearInterval(interval);
  }, [text, wordsPerTick, tickMs]);

  return wordsRef.current.slice(0, visibleWordCount).join("");
}
