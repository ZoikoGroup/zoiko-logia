import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
import { DesktopSidebar } from "@/components/ask-kriton/Sidebar";

function renderSidebar() {
  const handlers = { onOpenChats: vi.fn(), onNewChat: vi.fn(), onOpenProjects: vi.fn(), onOpenSources: vi.fn() };
  render(
    <DesktopSidebar
      conversations={[]} activeId={null} showMenu
      onSelect={vi.fn()} onPin={vi.fn()} onRename={vi.fn()} onDownload={vi.fn()} onDelete={vi.fn()}
      {...handlers}
    />,
  );
  return handlers;
}

describe("Kriton sidebar", () => {
  it("opens the chats panel from Chats; the sidebar has no separate search icon", () => {
    const handlers = renderSidebar();
    fireEvent.click(screen.getByText("Chats"));
    expect(handlers.onOpenChats).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Search chats" })).toBeNull();
  });

  it("wires New chat, Projects and Sources", () => {
    const handlers = renderSidebar();
    fireEvent.click(screen.getByText("New chat"));
    fireEvent.click(screen.getByText("Projects"));
    fireEvent.click(screen.getByText("Sources"));
    expect(handlers.onNewChat).toHaveBeenCalled();
    expect(handlers.onOpenProjects).toHaveBeenCalled();
    expect(handlers.onOpenSources).toHaveBeenCalled();
  });
});
