import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
afterEach(() => vi.useRealTimers());
it("does not refetch on focus or a timer; live pages retain manual refresh", () => {
  vi.useFakeTimers();
  const reload = vi.fn();
  render(<LiveSourceStatus loading={false} error="" signedOut={false} reload={reload} />);
  act(() => vi.advanceTimersByTime(120_000));
  fireEvent(window, new Event("focus"));
  expect(reload).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(reload).toHaveBeenCalledTimes(1);
});
it("removes catalog refresh but preserves error recovery", () => {
  const reload = vi.fn();
  const { rerender } = render(<LiveSourceStatus loading={false} error="" signedOut={false} reload={reload} showRefresh={false} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  rerender(<LiveSourceStatus loading={false} error="Unavailable" signedOut={false} reload={reload} showRefresh={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(reload).toHaveBeenCalledTimes(1);
});
it("does not request records after sign-out", () => {
  const reload = vi.fn();
  render(<LiveSourceStatus loading={false} error="" signedOut reload={reload} />);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(reload).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
});
