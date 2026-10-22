import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/",
  replace: vi.fn(),
  auth: {
    session: { user: { id: "u1" } },
    loading: false,
    profile: null as object | null,
    profileLoading: false,
    profileError: "Account not provisioned — sign in again to complete setup",
    refreshProfile: vi.fn(),
    signOut: vi.fn(),
  },
}));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: state.replace }),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => state.auth }));
import { AuthGuard } from "@/components/AuthGuard";

beforeEach(() => {
  vi.clearAllMocks();
  state.pathname = "/";
  state.auth.profile = null;
  state.auth.profileLoading = false;
});

it("blocks protected components and exposes recovery after profile refusal", () => {
  render(<AuthGuard><p>Protected requests</p></AuthGuard>);
  expect(screen.queryByText("Protected requests")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Account not provisioned");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(state.auth.refreshProfile).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(state.auth.signOut).toHaveBeenCalledOnce();
});

it("waits for initial profile verification before mounting protected components", () => {
  state.auth.profileLoading = true;
  render(<AuthGuard><p>Protected requests</p></AuthGuard>);
  expect(screen.queryByText("Protected requests")).not.toBeInTheDocument();
});

it("allows verified profiles and public account setup pages", () => {
  state.auth.profile = { id: "u1" };
  const view = render(<AuthGuard><p>Workspace</p></AuthGuard>);
  expect(screen.getByText("Workspace")).toBeInTheDocument();
  state.auth.profile = null;
  state.pathname = "/auth/callback";
  view.rerender(<AuthGuard><p>Complete setup</p></AuthGuard>);
  expect(screen.getByText("Complete setup")).toBeInTheDocument();
});
