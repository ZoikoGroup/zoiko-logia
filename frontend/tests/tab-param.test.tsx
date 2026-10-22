import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/source-library",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
import { useTabParam } from "@/components/shell/useTabParam";

afterEach(() => { window.history.replaceState(null, "", "/"); });

it("changes client tabs without server navigation, preserving other URL state", () => {
  window.history.replaceState(null, "", "/source-library?record=42#inspector");
  const { result, rerender } = renderHook(() => useTabParam("all", ["all", "licensing"]));
  act(() => result.current[1]("licensing"));
  rerender();
  expect(result.current[0]).toBe("licensing");
  expect(window.location.search).toBe("?record=42&tab=licensing");
  expect(window.location.hash).toBe("#inspector");
  act(() => result.current[1]("all"));
  rerender();
  expect(result.current[0]).toBe("all");
  expect(window.location.search).toBe("?record=42");
});
