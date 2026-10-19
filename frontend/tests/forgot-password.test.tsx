import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ resetPassword: vi.fn().mockResolvedValue(undefined) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/layout/AppHeader", () => ({ BrandMark: () => null }));
vi.mock("@/services/auth.service", () => ({
  AuthError: class extends Error {},
  resetPassword: auth.resetPassword,
}));

import ForgotPasswordPage from "@/app/auth/forgot-password/page";

describe("Forgot password (emailed reset link)", () => {
  it("refuses a malformed email without sending anything", async () => {
    render(<ForgotPasswordPage />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "not-an-email" } });
    // Submit the form directly: jsdom's type="email" validation would block a click.
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the email address");
    expect(auth.resetPassword).not.toHaveBeenCalled();
  });

  it("sends a reset link and confirms without revealing whether the account exists", async () => {
    render(<ForgotPasswordPage />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " ada@example.com " } });
    fireEvent.click(screen.getByRole("button", { name: /Send reset link/ }));
    await waitFor(() => expect(auth.resetPassword).toHaveBeenCalledWith("ada@example.com"));
    expect(await screen.findByText("Reset link sent")).toBeInTheDocument();
    expect(screen.getByText(/If an account exists for/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resend link in/ })).toBeDisabled();
  });
});
