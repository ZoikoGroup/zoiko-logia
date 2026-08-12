"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  Download,
  FolderKanban,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import type { Conversation } from "@/lib/ask-kriton-storage";

function ZoikoGlyph({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <div className={`${className} relative shrink-0 overflow-hidden rounded-xl bg-[#16799A] shadow-[0_18px_44px_rgba(0,0,0,0.28)]`}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_18%,rgba(255,255,255,0.32),transparent_34%)]" />
      <div className="absolute left-[25%] top-[26%] h-[48%] w-[50%] rounded-sm border-[3px] border-white" />
      <div className="absolute bottom-[31%] left-[36%] h-[26%] w-[8%] bg-[#F3C437]" />
      <div className="absolute bottom-[31%] left-[48%] h-[26%] w-[8%] bg-[#F3C437]" />
      <div className="absolute bottom-[31%] left-[60%] h-[26%] w-[8%] bg-[#F3C437]" />
    </div>
  );
}

function NavRow({ icon: Icon, label, href, onClick }: { icon: typeof MessageSquare; label: string; href?: string; onClick?: () => void }) {
  const content = (
    <span className="flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink transition hover:bg-soft">
      <Icon size={17} className="text-muted" />
      <span className="truncate">{label}</span>
    </span>
  );
  return href ? <Link href={href}>{content}</Link> : (
    <button type="button" onClick={onClick} className="w-full text-left">{content}</button>
  );
}

function RecentRow({
  conversation,
  active,
  showMenu,
  menuOpen,
  renaming,
  onSelect,
  onToggleMenu,
  onPin,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onDownload,
  onDelete,
}: {
  conversation: Conversation;
  active: boolean;
  showMenu: boolean;
  menuOpen: boolean;
  renaming: boolean;
  onSelect: () => void;
  onToggleMenu: () => void;
  onPin: () => void;
  onStartRename: () => void;
  onCommitRename: (title: string) => void;
  onCancelRename: () => void;
  onDownload: () => void;
  onDelete: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  if (renaming) {
    // Uncontrolled — the callback ref fires exactly at mount, so it can
    // focus/select without a useEffect syncing state from the `renaming` prop.
    return (
      <input
        ref={(node) => {
          inputRef.current = node;
          node?.focus();
          node?.select();
        }}
        defaultValue={conversation.title}
        onBlur={() => onCommitRename(inputRef.current?.value.trim() || conversation.title)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); onCommitRename(inputRef.current?.value.trim() || conversation.title); }
          if (e.key === "Escape") { e.preventDefault(); onCancelRename(); }
        }}
        className="h-9 w-full rounded-lg border border-brand/40 bg-panel px-2 text-sm font-medium text-ink outline-none"
      />
    );
  }

  return (
    <div className={`group relative flex h-9 items-center gap-1.5 rounded-lg pr-1 ${active ? "bg-panel text-ink" : "text-muted hover:bg-panel/60"}`}>
      <button type="button" onClick={onSelect} className="flex min-w-0 flex-1 items-center gap-1.5 px-2 text-left text-sm font-medium">
        {conversation.pinned && <Pin size={11} className="shrink-0 text-brand" />}
        <span className="truncate">{conversation.title}</span>
      </button>
      {showMenu && (
        <div className="relative shrink-0">
          <button
            type="button"
            onClick={onToggleMenu}
            aria-label="More options"
            className={`flex h-7 w-7 items-center justify-center rounded-md hover:bg-soft ${menuOpen ? "bg-soft" : "opacity-0 group-hover:opacity-100"}`}
          >
            <MoreHorizontal size={15} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full z-20 mt-1 w-40 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-xl">
              <button type="button" onClick={onPin} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-ink hover:bg-soft">
                {conversation.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                {conversation.pinned ? "Unpin" : "Pin"}
              </button>
              <button type="button" onClick={onStartRename} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-ink hover:bg-soft">
                <Pencil size={13} />
                Rename
              </button>
              <button type="button" onClick={onDownload} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-ink hover:bg-soft">
                <Download size={13} />
                Download .md
              </button>
              {/* Destructive action last and visually separated, so it is not
                  adjacent to the action a user reaches for most often. */}
              <div className="my-1 border-t border-line" />
              <button type="button" onClick={onDelete} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-bad hover:bg-bad/10">
                <Trash2 size={13} />
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export type RecentsListProps = {
  conversations: Conversation[];
  activeId: string | null;
  showMenu: boolean;
  onSelect: (id: string) => void;
  onPin: (id: string) => void;
  onRename: (id: string, title: string) => void;
  /** Export one thread as markdown. The sidebar only signals intent — the page
   * owns the conversation data and the rendering, same as rename and delete. */
  onDownload: (id: string) => void;
  onDelete: (id: string) => void;
};

export function RecentsList({
  conversations,
  activeId,
  showMenu,
  onSelect,
  onPin,
  onRename,
  onDownload,
  onDelete,
}: RecentsListProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);

  if (conversations.length === 0) {
    return <p className="px-2 py-1 text-xs text-muted">No chats yet — ask a question to start one.</p>;
  }

  return (
    <div className="space-y-1">
      {conversations.map((c) => (
        <RecentRow
          key={c.id}
          conversation={c}
          active={c.id === activeId}
          showMenu={showMenu}
          menuOpen={openMenuId === c.id}
          renaming={renamingId === c.id}
          onSelect={() => onSelect(c.id)}
          onToggleMenu={() => setOpenMenuId((v) => (v === c.id ? null : c.id))}
          onPin={() => { onPin(c.id); setOpenMenuId(null); }}
          onStartRename={() => { setRenamingId(c.id); setOpenMenuId(null); }}
          onCommitRename={(title) => { onRename(c.id, title); setRenamingId(null); }}
          onCancelRename={() => setRenamingId(null)}
          onDownload={() => { onDownload(c.id); setOpenMenuId(null); }}
          onDelete={() => { onDelete(c.id); setOpenMenuId(null); }}
        />
      ))}
    </div>
  );
}

export function DesktopSidebar(props: RecentsListProps & { onNewChat: () => void }) {
  return (
    <aside className="kriton-sidebar-background hidden min-h-0 border-r border-line md:flex md:flex-col">
      <div className="flex items-center justify-between px-5 py-5">
        <div className="flex items-center gap-3">
          <ZoikoGlyph className="h-9 w-9 rounded-lg" />
          <div>
            <div className="text-lg font-bold tracking-normal text-ink">Kriton</div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">ZoikoLogia</div>
          </div>
        </div>
        <Search size={17} className="text-muted" />
      </div>

      <nav className="space-y-1 px-3">
        <NavRow icon={Plus} label="New chat" onClick={props.onNewChat} />
        <NavRow icon={MessageSquare} label="Chats" />
        <NavRow icon={FolderKanban} label="Projects" href="/my-workspace" />
        <NavRow icon={BookOpen} label="Sources" href="/source-licensing" />
      </nav>

      <div className="mt-6 flex min-h-0 flex-1 flex-col px-5">
        <p className="mb-2 text-xs font-bold text-muted">Recents</p>
        <div className="min-h-0 space-y-1 overflow-y-auto pr-1">
          <RecentsList {...props} />
        </div>
      </div>

      <div className="border-t border-line px-5 py-4">
        <Link href="/" className="text-xs font-semibold text-muted hover:text-ink">
          ← Back to Dashboard
        </Link>
      </div>
    </aside>
  );
}

export function MobileDrawer(props: RecentsListProps & { onNewChat: () => void; open: boolean; onClose: () => void }) {
  if (!props.open) return null;
  return (
    <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={props.onClose} />
      <div className="kriton-sidebar-background relative flex h-full w-[86%] max-w-xs flex-col border-r border-line shadow-2xl">
        <div className="flex items-center justify-between px-5 py-5">
          <div className="flex items-center gap-3">
            <ZoikoGlyph className="h-8 w-8 rounded-lg" />
            <div className="text-base font-bold text-ink">Kriton</div>
          </div>
          <button onClick={props.onClose} aria-label="Close menu" className="rounded-lg p-1.5 text-muted hover:bg-soft">
            <X size={18} />
          </button>
        </div>
        <nav className="space-y-1 px-3">
          <NavRow icon={Plus} label="New chat" onClick={() => { props.onNewChat(); props.onClose(); }} />
        </nav>
        <div className="mt-6 flex min-h-0 flex-1 flex-col px-5">
          <p className="mb-2 text-xs font-bold text-muted">Recents</p>
          <div className="min-h-0 space-y-1 overflow-y-auto pr-1">
            <RecentsList {...props} showMenu={false} onSelect={(id) => { props.onSelect(id); props.onClose(); }} />
          </div>
        </div>
      </div>
    </div>
  );
}
