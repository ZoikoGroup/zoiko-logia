import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
afterEach(() => vi.useRealTimers());
it("refreshes on the minute, on focus, and on demand; stops when unmounted", () => {
  vi.useFakeTimers();
  const reload = vi.fn();
  const { unmount } = render(<LiveSourceStatus loading={false} error="" signedOut={false} reload={reload} />);
  act(() => vi.advanceTimersByTime(60_000));
  expect(reload).toHaveBeenCalledTimes(1);
  fireEvent(window, new Event("focus"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(reload).toHaveBeenCalledTimes(3);
  unmount();
  act(() => vi.advanceTimersByTime(60_000));
  expect(reload).toHaveBeenCalledTimes(3);
});
it("does not request records after sign-out", () => {
  vi.useFakeTimers();
  const reload = vi.fn();
  const { unmount } = render(<LiveSourceStatus loading={false} error="" signedOut reload={reload} />);
  act(() => vi.advanceTimersByTime(120_000));
  fireEvent(window, new Event("focus"));
  expect(reload).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  unmount();
});
