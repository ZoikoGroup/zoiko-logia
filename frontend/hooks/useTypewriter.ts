"use client";

import { useEffect, useMemo, useState } from "react";

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
  const words = useMemo(
    () => text.split(/(\s+)/),
    [text],
  );

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    if (prefersReducedMotion || words.length === 0) {
      setVisibleWordCount(words.length);
      return;
    }

    setVisibleWordCount(0);
    const interval = setInterval(() => {
      setVisibleWordCount((count) => {
        const next = count + wordsPerTick;
        if (next >= words.length) {
          clearInterval(interval);
          return words.length;
        }
        return next;
      });
    }, tickMs);

    return () => clearInterval(interval);
  }, [words, wordsPerTick, tickMs]);

  return words.slice(0, visibleWordCount).join("");
}
