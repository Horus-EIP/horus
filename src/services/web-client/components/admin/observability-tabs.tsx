'use client';

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconChartArea, IconBinaryTree2, IconLogs } from "@tabler/icons-react";

const TABS = [
  { href: "/admin/logs", label: "Logs", icon: IconLogs },
  { href: "/admin/metrics", label: "Metrics", icon: IconChartArea },
  { href: "/admin/traces", label: "Traces", icon: IconBinaryTree2 },
];

/** Sub-navigation shared by the admin observability pages (logs / metrics / traces). */
export function ObservabilityTabs() {
  const pathname = usePathname();
  return (
    <div className="flex flex-wrap items-center gap-2">
      {TABS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname?.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm shadow cursor-pointer ${
              active
                ? "bg-blue-600 text-white"
                : "bg-white/5 text-[var(--text)] hover:bg-white/10"
            }`}
          >
            <Icon size={16} />
            {label}
          </Link>
        );
      })}
    </div>
  );
}
