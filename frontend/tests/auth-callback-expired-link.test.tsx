import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Bug 1 of "Logia platform bugs" (10 Nov 2026): a sign-up confirmation link
// that had expired left the person with no way to get a new one.
const auth = vi.hoisted(() => ({ resend: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { getSession: vi.fn(), onAuthStateChange: vi.fn(), signOut: vi.fn() } } }));
vi.mock("@/components/layout/AppHeader", () => ({ BrandMark: () => null }));
vi.mock("@/services/auth.service", () => ({
  mfaChallengeRequired: vi.fn(), provisionAndRefresh: vi.fn(), resendConfirmation: auth.resend,
}));
import AuthCallbackPage from "@/app/auth/callback/page";

afterEach(() => window.history.replaceState({}, "", "/"));

describe("an expired confirmation link", () => {
  it("says so and sends a new confirmation email", async () => {
    auth.resend.mockResolvedValue(undefined);
    window.history.replaceState({}, "", "/auth/callback?error=access_denied&error_code=otp_expired"
      + "&error_description=Email+link+is+invalid+or+has+expired");
    render(<AuthCallbackPage />);
    expect(await screen.findByText(/This confirmation link has expired or was already used/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "new.user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send a new confirmation email" }));
    await waitFor(() => expect(auth.resend).toHaveBeenCalledWith("new.user@example.com"));
    expect(await screen.findByRole("status")).toHaveTextContent("A new confirmation email is on its way");
  });

  it("shows another link error without the resend form", async () => {
    window.history.replaceState({}, "", "/auth/callback?error=server_error&error_description=Database+error");
    render(<AuthCallbackPage />);
    expect(await screen.findByText(/Database error\. Please sign in, or request a new link\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send a new confirmation email" })).not.toBeInTheDocument();
  });
});
