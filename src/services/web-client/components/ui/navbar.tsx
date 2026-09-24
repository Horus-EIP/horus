'use client';

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  IconBell,
  IconLayoutSidebar,
  IconSearch,
  IconSun,
} from "@tabler/icons-react";

type NavbarProps = {
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
};

export default function Navbar({ onToggleSidebar, sidebarOpen }: NavbarProps) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((s) => !s);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const title = (pathname?.startsWith('/404') || pathname?.startsWith('/500')) ? "" : pathname?.split("/").filter(Boolean).pop() ?? "";

  return (
    <>
      <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-[var(--bgSoft)]/80 p-3 shadow-xl backdrop-blur-xl">
        <div className="flex items-center gap-3 text-[var(--textSoft)] font-semibold capitalize">
            <button
                type="button"
                onClick={onToggleSidebar}
                aria-pressed={sidebarOpen}
                className="rounded-lg p-1.5 hover:bg-white/10 text-[var(--text)]"
            >
            <IconLayoutSidebar size={20} className="text-[var(--text)] my-auto rotate-y-180" stroke={1.25} />
            </button>
            <span>{title}</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setOpen(true)}
            className="group hidden sm:flex items-center gap-2 rounded-xl border border-white/10 bg-black/10 px-3 py-2 text-sm text-[var(--textSoft)] outline-none transition hover:bg-black/20 min-w-[200px]"
            aria-label="Open command palette"
            title="Ctrl/⌘ + K"
          >
            <IconSearch size={18} stroke={1.25} />
            <span>Search…</span>
            {/* <kbd className="ml-2 rounded bg-black/30 px-1.5 py-0.5 text-xs">Ctrl/⌘ K</kbd> */}
          </button>
          <div className="flex items-center gap-4 text-[var(--text)]">
            <IconSun size={18} className="opacity-80 hover:opacity-100 transition" stroke={1.25} />
            <IconBell size={18} className="opacity-80 hover:opacity-100 transition" stroke={1.25} />
          </div>
        </div>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 grid place-items-start bg-black/40 p-4 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <div className="mx-auto w-full max-w-2xl rounded-2xl border border-white/10 bg-[var(--bgSoft)] p-2 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/10 px-3 py-2">
              <IconSearch size={18} stroke={1.25} />
              <input
                autoFocus
                placeholder="Busque páginas, agentes, tarefas…"
                className="w-full bg-transparent outline-none text-sm"
              />
            </div>
            <div className="mt-2 max-h-[50vh] overflow-y-auto text-sm">
              <p className="px-3 py-2 text-[var(--textSoft)]">Sugestões</p>
              <ul className="grid gap-1 p-1">
                {[
                  { label: "Go to Dashboard", href: "/dashboard" },
                  { label: "Open Chat", href: "/chat" },
                  { label: "Knowledge Store", href: "/knowledge-store" },
                ].map((it) => (
                  <li key={it.href}>
                    <a
                      className="block rounded-lg px-3 py-2 hover:bg-white/5"
                      href={it.href}
                      onClick={() => setOpen(false)}
                    >
                      {it.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </>
  );
}