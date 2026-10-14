import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useConversationScroll } from "@/hooks/useConversationScroll";

function scrollBox() {
  const box = document.createElement("div");
  Object.defineProperties(box, { scrollHeight: { value: 2000 }, clientHeight: { value: 500 } });
  box.scrollTo = vi.fn();
  return box;
}

it("keeps an earlier sent question visible when the current answer finishes", () => {
  const { result, rerender } = renderHook(({ loading }) => useConversationScroll("chat-a", 2, loading), { initialProps: { loading: true } });
  const box = scrollBox();
  result.current.scrollRef.current = box;
  box.scrollTop = 0;
  act(() => result.current.onScroll());
  rerender({ loading: false });
  expect(box.scrollTo).not.toHaveBeenCalled();
});

it("follows completion at the bottom and shows a newly submitted turn", () => {
  const { result, rerender } = renderHook(({ count, loading }) => useConversationScroll("chat-a", count, loading), { initialProps: { count: 2, loading: true } });
  const box = scrollBox();
  result.current.scrollRef.current = box;
  box.scrollTop = 1500;
  act(() => result.current.onScroll());
  rerender({ count: 2, loading: false });
  expect(box.scrollTo).toHaveBeenLastCalledWith({ top: 2000, behavior: "smooth" });
  box.scrollTop = 0;
  act(() => result.current.onScroll());
  rerender({ count: 3, loading: true });
  expect(box.scrollTo).toHaveBeenLastCalledWith({ top: 2000, behavior: "instant" });
});
