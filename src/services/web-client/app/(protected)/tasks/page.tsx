'use client';

import { useEffect, useState, useCallback } from "react";
import { chatApi, TaskQueueStats, type TaskSummary } from "@/lib/chat/api";
import Card from "@/components/ui/card";
import { useNotification } from "@/contexts/notification-context";
import { useAuth } from "@/components/auth/auth-provider";
import Link from 'next/link';
import {
  IconClock,
  IconPlayerPlay,
  IconCheck,
  IconX,
  IconBan,
  IconAlertTriangle,
  IconPlus,
  IconRefresh,
  IconChevronRight,
} from '@tabler/icons-react';

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}

function StatCard({ title, value, icon, color, bgColor }: StatCardProps) {
  return (
    <div className={`rounded-2xl border border-white/10 ${bgColor} p-4 flex items-center gap-4`}>
      <div className={`p-3 rounded-xl ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-[var(--textSoft)] text-sm">{title}</p>
        <p className="text-[var(--text)] text-2xl font-bold">{value}</p>
      </div>
    </div>
  );
}

const STATUS_PILL: Record<string, string> = {
  completed: 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30',
  running: 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30',
  pending: 'bg-white/10 text-[var(--textSoft)] ring-1 ring-white/10',
  failed: 'bg-red-500/20 text-red-300 ring-1 ring-red-500/30',
  cancelled: 'bg-gray-500/20 text-gray-300 ring-1 ring-gray-500/30',
  canceled: 'bg-gray-500/20 text-gray-300 ring-1 ring-gray-500/30',
};

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = Date.now() - then;
  const seconds = Math.round(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export default function TasksPage() {
  const [stats, setStats] = useState<TaskQueueStats | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const { error: notifyError } = useNotification();
  const { user } = useAuth();

  const loadAll = useCallback(async () => {
    try {
      setIsLoading(true);
      const [statsRes, listRes] = await Promise.all([
        chatApi.getTaskQueueStats(),
        chatApi.listTasks(),
      ]);
      if (statsRes.ok && statsRes.data) {
        setStats(statsRes.data);
      } else {
        notifyError(statsRes.error || "Failed to load task queue stats");
      }
      if (listRes.ok && listRes.data) {
        // Newest first.
        const sorted = [...listRes.data].sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
        setTasks(sorted);
      }
      setLastUpdated(new Date());
    } catch (e) {
      notifyError("Failed to load task queue stats");
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadAll();
    // Auto-refresh every 10 seconds.
    const interval = setInterval(loadAll, 10000);
    return () => clearInterval(interval);
  }, [loadAll]);

  const canViewTasks = () => {
    return user?.role === 'admin' || user?.role === 'manager';
  };

  if (!canViewTasks()) {
    return (
      <div className="p-4 md:p-6">
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-6 text-center">
          <IconBan className="w-12 h-12 mx-auto mb-4 text-[var(--textSoft)]" />
          <p className="text-[var(--textSoft)]">
            You don't have permission to view task queue statistics.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Task Queue</h1>
          {lastUpdated && (
            <p className="text-sm text-[var(--textSoft)]">
              Last updated: {lastUpdated.toLocaleTimeString()}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/tasks/new"
            className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm text-white shadow hover:bg-blue-700"
          >
            <IconPlus className="h-4 w-4" />
            New task
          </Link>
          <button
            onClick={loadAll}
            disabled={isLoading}
            className="rounded-xl bg-white/5 px-4 py-2 text-sm text-white shadow hover:bg-white/10 cursor-pointer flex items-center gap-2 disabled:opacity-50"
          >
            <IconRefresh className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {isLoading && !stats ? (
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 text-[var(--textSoft)]">
          Loading task queue statistics...
        </div>
      ) : stats ? (
        <>
          {/* Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            <StatCard
              title="Pending"
              value={stats.pending}
              icon={<IconClock className="w-6 h-6 text-yellow-400" />}
              color="bg-yellow-500/20"
              bgColor="bg-[var(--bgSoft)]/70"
            />
            <StatCard
              title="Running"
              value={stats.running}
              icon={<IconPlayerPlay className="w-6 h-6 text-blue-400" />}
              color="bg-blue-500/20"
              bgColor="bg-[var(--bgSoft)]/70"
            />
            <StatCard
              title="Completed"
              value={stats.completed}
              icon={<IconCheck className="w-6 h-6 text-green-400" />}
              color="bg-green-500/20"
              bgColor="bg-[var(--bgSoft)]/70"
            />
            <StatCard
              title="Failed"
              value={stats.failed}
              icon={<IconX className="w-6 h-6 text-red-400" />}
              color="bg-red-500/20"
              bgColor="bg-[var(--bgSoft)]/70"
            />
            <StatCard
              title="Cancelled"
              value={stats.cancelled}
              icon={<IconBan className="w-6 h-6 text-gray-400" />}
              color="bg-gray-500/20"
              bgColor="bg-[var(--bgSoft)]/70"
            />
            <StatCard
              title="Timeout"
              value={stats.timeout}
              icon={<IconAlertTriangle className="w-6 h-6 text-orange-400" />}
              color="bg-orange-500/20"
              bgColor="bg-[var(--bgSoft)]/70"
            />
          </div>

          {/* Total Summary */}
          <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[var(--textSoft)] text-sm">Total Tasks</p>
                <p className="text-[var(--text)] text-3xl font-bold">{stats.total}</p>
              </div>
              <div className="flex gap-4">
                <div className="text-center">
                  <p className="text-[var(--textSoft)] text-xs">Success Rate</p>
                  <p className="text-green-400 text-xl font-bold">
                    {stats.total > 0 
                      ? Math.round((stats.completed / stats.total) * 100) 
                      : 0}%
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-[var(--textSoft)] text-xs">Active</p>
                  <p className="text-blue-400 text-xl font-bold">
                    {stats.pending + stats.running}
                  </p>
                </div>
              </div>
            </div>

            {/* Progress bar visualization */}
            <div className="mt-4">
              <div className="flex h-4 rounded-full overflow-hidden bg-white/5">
                {stats.completed > 0 && (
                  <div 
                    className="bg-green-500 transition-all duration-500"
                    style={{ width: `${(stats.completed / stats.total) * 100}%` }}
                    title={`Completed: ${stats.completed}`}
                  />
                )}
                {stats.running > 0 && (
                  <div 
                    className="bg-blue-500 transition-all duration-500"
                    style={{ width: `${(stats.running / stats.total) * 100}%` }}
                    title={`Running: ${stats.running}`}
                  />
                )}
                {stats.pending > 0 && (
                  <div 
                    className="bg-yellow-500 transition-all duration-500"
                    style={{ width: `${(stats.pending / stats.total) * 100}%` }}
                    title={`Pending: ${stats.pending}`}
                  />
                )}
                {stats.failed > 0 && (
                  <div 
                    className="bg-red-500 transition-all duration-500"
                    style={{ width: `${(stats.failed / stats.total) * 100}%` }}
                    title={`Failed: ${stats.failed}`}
                  />
                )}
                {stats.cancelled > 0 && (
                  <div 
                    className="bg-gray-500 transition-all duration-500"
                    style={{ width: `${(stats.cancelled / stats.total) * 100}%` }}
                    title={`Cancelled: ${stats.cancelled}`}
                  />
                )}
                {stats.timeout > 0 && (
                  <div 
                    className="bg-orange-500 transition-all duration-500"
                    style={{ width: `${(stats.timeout / stats.total) * 100}%` }}
                    title={`Timeout: ${stats.timeout}`}
                  />
                )}
              </div>
              <div className="flex justify-between mt-2 text-xs text-[var(--textSoft)]">
                <div className="flex gap-4">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-green-500"></span> Completed
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-blue-500"></span> Running
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-yellow-500"></span> Pending
                  </span>
                </div>
                <div className="flex gap-4">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-red-500"></span> Failed
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-gray-500"></span> Cancelled
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-orange-500"></span> Timeout
                  </span>
                </div>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 text-[var(--textSoft)]">
          No task queue data available.
        </div>
      )}

      {/* Recent tasks — click any row to jump to its detail page. */}
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 md:p-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-[var(--text)]">Recent tasks</h2>
          <span className="text-xs text-[var(--textSoft)]">
            {tasks.length} total
          </span>
        </div>
        {tasks.length === 0 ? (
          <p className="text-sm text-[var(--textSoft)]">
            No tasks yet. Dispatch one from{' '}
            <Link href="/tasks/new" className="underline">
              /tasks/new
            </Link>
            .
          </p>
        ) : (
          <ul className="divide-y divide-white/5">
            {tasks.slice(0, 50).map((t) => {
              const pill = STATUS_PILL[t.status] ?? STATUS_PILL.pending;
              const title =
                t.query.length > 110
                  ? `${t.query.slice(0, 110)}…`
                  : t.query;
              return (
                <li key={t.id}>
                  <Link
                    href={`/tasks/${t.id}`}
                    className="group flex items-center gap-3 py-2.5 hover:bg-white/5 rounded-lg px-2 -mx-2 transition"
                  >
                    <span
                      className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full font-medium shrink-0 ${pill}`}
                    >
                      {t.status}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-[var(--text)] truncate">
                        {title || '(empty demand)'}
                      </p>
                      <p className="text-xs text-[var(--textSoft)] mt-0.5">
                        {formatRelative(t.created_at)} · agent {t.agent_id.slice(0, 8)}…
                      </p>
                    </div>
                    <IconChevronRight className="h-4 w-4 text-[var(--textSoft)] group-hover:text-[var(--text)] shrink-0" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
