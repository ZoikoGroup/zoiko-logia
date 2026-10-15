import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  request: vi.fn().mockResolvedValue({ message: "ok", expires_in_minutes: 15, code_length: 6 }),
  reset: vi.fn().mockResolvedValue({ message: "ok" }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/layout/AppHeader", () => ({ BrandMark: () => null }));
vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {},
  requestPasswordResetCode: api.request,
  resetPasswordWithCode: api.reset,
}));

import ForgotPasswordPage from "@/app/auth/forgot-password/page";

describe("Forgot password (emailed code)", () => {
  it("sends a code, then resets only with a full code and matching strong passwords", async () => {
    render(<ForgotPasswordPage />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /Send code/ }));
    await waitFor(() => expect(api.request).toHaveBeenCalledWith("ada@example.com"));
    expect(await screen.findByText("Enter your code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resend code in/ })).toBeDisabled();

    const submit = screen.getByRole("button", { name: "Set new password" });
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "12345" } });
    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "Secure123" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "Secure123" } });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "Secure124" } });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "Secure123" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(api.reset).toHaveBeenCalledWith("ada@example.com", "123456", "Secure123"));
    expect(await screen.findByText("Your password is set")).toBeInTheDocument();
  });
});
