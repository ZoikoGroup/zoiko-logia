import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const navigation = vi.hoisted(() => ({ pathname: "/", pending: false, push: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname, useRouter: () => ({ push: navigation.push }) }));
vi.mock("next/link", () => ({
  default: ({ children, onNavigate, ...props }: { children: ReactNode; onNavigate?: () => void; href: string }) => <a {...props} onClick={e => { e.preventDefault(); onNavigate?.(); }}>{children}</a>,
  useLinkStatus: () => ({ pending: navigation.pending }),
}));
vi.mock("@/components/shell/RoleProvider", () => ({ useRole: () => ({ role: "Admin", roleReady: true }) }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ signOut: vi.fn(), user: null, profile: { full_name: "Test Admin" } }) }));
import { Sidebar } from "@/components/layout/Sidebar";
beforeEach(() => { navigation.pathname = "/"; navigation.pending = false; });
describe("Sidebar responsiveness", () => {
  it("collapses and reopens the section containing the current page", () => {
    render(<Sidebar mobileOpen={false} onMobileClose={vi.fn()} />);
    const overview = screen.getByRole("button", { name: "Overview" });
    expect(overview).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(overview);
    expect(overview).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Command Center" })).not.toBeInTheDocument();
    fireEvent.click(overview);
    expect(overview).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Command Center" })).toHaveAttribute("aria-current", "page");
  });
  it("opens a directly visited section and lets the user close it", () => {
    navigation.pathname = "/source-library";
    render(<Sidebar mobileOpen={false} onMobileClose={vi.fn()} />);
    const sources = screen.getByRole("button", { name: "Source & Knowledge Governance" });
    expect(sources).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(sources);
    expect(sources).toHaveAttribute("aria-expanded", "false");
  });
  it("closes the mobile menu on navigation without waiting for the destination", () => {
    const close = vi.fn();
    render(<Sidebar mobileOpen={true} onMobileClose={close} />);
    close.mockClear();
    fireEvent.click(screen.getAllByRole("link", { name: "Governance Dashboard" })[1]);
    expect(close).toHaveBeenCalledOnce();
  });
  it("shows pending navigation and uses the original theme", () => {
    navigation.pending = true;
    const { container } = render(<Sidebar mobileOpen={false} onMobileClose={vi.fn()} />);
    expect(screen.getByText("Opening Command Center…")).toBeInTheDocument();
    expect(container.querySelector(".overview-sidebar")).toBeNull();
    expect(container.querySelector("aside")).toHaveClass("bg-panel");
  });
});
