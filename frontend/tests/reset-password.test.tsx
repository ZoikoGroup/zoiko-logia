import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ update: vi.fn().mockResolvedValue(undefined) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/layout/AppHeader", () => ({ BrandMark: () => null }));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: {
    getSession: async () => ({ data: { session: { user: { id: "u1" } } } }),
    onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }),
  } },
}));
vi.mock("@/services/auth.service", () => ({ AuthError: class extends Error {}, updatePassword: auth.update }));

import ResetPasswordPage from "@/app/auth/reset-password/page";

describe("Reset password", () => {
  it("asks for the new password twice and only submits when both match the rules", async () => {
    render(<ResetPasswordPage />);
    const newPassword = await screen.findByLabelText("New Password");
    const confirm = screen.getByLabelText("Confirm New Password");
    const submit = screen.getByRole("button", { name: "Set new password" });

    fireEvent.change(newPassword, { target: { value: "Secure123" } });
    fireEvent.change(confirm, { target: { value: "Secure124" } });
    expect(submit).toBeDisabled();
    expect(confirm).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(newPassword, { target: { value: "weak" } });
    fireEvent.change(confirm, { target: { value: "weak" } });
    expect(submit).toBeDisabled();

    fireEvent.change(newPassword, { target: { value: "Secure123" } });
    fireEvent.change(confirm, { target: { value: "Secure123" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(auth.update).toHaveBeenCalledWith("Secure123"));
    expect(await screen.findByText("Your password is set")).toBeInTheDocument();
  });
});
