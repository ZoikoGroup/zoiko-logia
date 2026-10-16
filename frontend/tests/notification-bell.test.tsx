import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  summary: vi.fn(),
  list: vi.fn(),
  markOne: vi.fn(),
  markAll: vi.fn(),
}));
const push = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  getAuthToken: () => "token",
  getNotificationSummary: api.summary,
  listNotifications: api.list,
  markNotificationRead: api.markOne,
  markAllNotificationsRead: api.markAll,
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ session: { user: { id: "u1" } } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, onClick }: { href: string; children: React.ReactNode; onClick?: () => void }) => (
    <a href={href} onClick={onClick}>{children}</a>
  ),
}));
import { NotificationBell } from "@/components/layout/NotificationBell";

const item = {
  id: "n1", kind: "review_assigned", severity: "warn", title: "A question needs your review",
  body: "Kriton sent an answer to human review.", link: "/review-tasks", created_at: "2026-10-14T05:00:00Z", read: false,
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  push.mockReset();
  api.list.mockResolvedValue([]);
  api.markOne.mockResolvedValue(undefined);
});

describe("Notification bell", () => {
  it("shows no badge when there is nothing new", async () => {
    api.summary.mockResolvedValue({ unread: 0, action_items: [] });
    render(<NotificationBell />);
    await waitFor(() => expect(api.summary).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("shows the unread count and the items that need action", async () => {
    api.summary.mockResolvedValue({
      unread: 3,
      action_items: [{ key: "reviews", count: 2, label: "2 questions waiting for review", link: "/review-tasks", severity: "warn" }],
    });
    api.list.mockResolvedValue([item]);
    render(<NotificationBell />);
    const button = await screen.findByRole("button", { name: "Notifications, 3 unread" });
    expect(screen.getByText("3")).toBeInTheDocument();

    fireEvent.click(button);
    expect(await screen.findByText("2 questions waiting for review")).toBeInTheDocument();
    expect(await screen.findByText("A question needs your review")).toBeInTheDocument();
  });

  it("marks an item read and opens its page", async () => {
    api.summary.mockResolvedValue({ unread: 1, action_items: [] });
    api.list.mockResolvedValue([item]);
    render(<NotificationBell />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    fireEvent.click(await screen.findByText("A question needs your review"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/review-tasks"));
    expect(api.markOne).toHaveBeenCalledWith("token", "n1");
  });
});
