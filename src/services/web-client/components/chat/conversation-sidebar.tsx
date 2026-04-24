'use client';

import { IconMessagePlus, IconTrash } from '@tabler/icons-react';
import type { Conversation } from '@/lib/chat/api';

export type ConversationSidebarProps = {
  conversations: Conversation[];
  selectedId: string;
  searchTerm: string;
  onSearchChange: (v: string) => void;
  onSelect: (id: number) => void;
  onNewChat: () => void;
  onDelete: (c: Conversation) => void;
  canDelete: (c: Conversation) => boolean;
  isLoading: boolean;
  onRefresh: () => void;
  newChatPending?: boolean;
};

export function ConversationSidebar({
  conversations,
  selectedId,
  searchTerm,
  onSearchChange,
  onSelect,
  onNewChat,
  onDelete,
  canDelete,
  isLoading,
  onRefresh,
  newChatPending = false,
}: ConversationSidebarProps) {
  const filtered = conversations.filter((c) => {
    const text = `${c.name ?? ''} ${c.id}`.toLowerCase();
    return text.includes(searchTerm.toLowerCase());
  });

  return (
    <aside className="flex w-full shrink-0 flex-col overflow-hidden rounded-lg border border-gray-200 bg-[var(--bgSoft)] dark:border-gray-800 md:w-72 md:max-w-[40vw]">
      <div className="flex items-center gap-2 border-b border-gray-200 p-3 dark:border-gray-800">
        <button
          type="button"
          onClick={onNewChat}
          disabled={newChatPending}
          className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <IconMessagePlus className="h-4 w-4" stroke={1.5} />
          {newChatPending ? 'Creating…' : 'New chat'}
        </button>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="rounded-lg border border-gray-200 px-2 py-2 text-sm text-[var(--textSoft)] transition hover:bg-black/5 dark:border-gray-700 dark:hover:bg-white/5"
          aria-label="Refresh conversations"
          title="Refresh"
        >
          ↻
        </button>
      </div>
      <input
        type="search"
        placeholder="Search…"
        value={searchTerm}
        onChange={(e) => onSearchChange(e.target.value)}
        className="mx-3 mt-2 rounded-lg border border-gray-200 bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--textSoft)] dark:border-gray-700"
      />
      <div className="mt-2 flex-1 overflow-y-auto p-2">
        {isLoading && filtered.length === 0 ? (
          <p className="px-2 py-4 text-sm text-[var(--textSoft)]">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="px-2 py-4 text-sm text-[var(--textSoft)]">No conversations yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {filtered.map((c) => {
              const active = String(c.id) === selectedId;
              return (
                <li key={c.id} className="flex items-stretch gap-1">
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className={`min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm transition ${
                      active
                        ? 'bg-blue-600/20 font-medium text-[var(--text)] ring-1 ring-blue-500/40'
                        : 'text-[var(--text)] hover:bg-black/5 dark:hover:bg-white/5'
                    }`}
                  >
                    <span className="line-clamp-2">{c.name || `Conversation ${c.id}`}</span>
                    <span className="mt-0.5 block text-[10px] text-[var(--textSoft)]">#{c.id}</span>
                  </button>
                  {canDelete(c) && (
                    <button
                      type="button"
                      onClick={() => onDelete(c)}
                      className="flex w-9 shrink-0 items-center justify-center rounded-lg text-[var(--textSoft)] transition hover:bg-red-500/15 hover:text-red-400"
                      aria-label={`Delete conversation ${c.id}`}
                    >
                      <IconTrash className="h-4 w-4" stroke={1.25} />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
