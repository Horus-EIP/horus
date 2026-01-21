'use client';

import { useEffect, useState, useCallback } from "react";
import { chatApi, TaskQueueStats } from "@/lib/chat/api";
import Card from "@/components/ui/card";
import { useNotification } from "@/contexts/notification-context";
import { useAuth } from "@/components/auth/auth-provider";
import { 
  IconClock, 
  IconPlayerPlay, 
  IconCheck, 
  IconX, 
  IconBan,
  IconAlertTriangle,
  IconRefresh
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

export default function TasksPage() {
  const [stats, setStats] = useState<TaskQueueStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  
  const { error: notifyError } = useNotification();
  const { user } = useAuth();

  const loadStats = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await chatApi.getTaskQueueStats();
      if (result.ok && result.data) {
        setStats(result.data);
        setLastUpdated(new Date());
      } else {
        notifyError(result.error || "Failed to load task queue stats");
      }
    } catch (e) {
      notifyError("Failed to load task queue stats");
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadStats();
    
    // Auto-refresh every 10 seconds
    const interval = setInterval(loadStats, 10000);
    return () => clearInterval(interval);
  }, [loadStats]);

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
        <button
          onClick={loadStats}
          disabled={isLoading}
          className="rounded-xl bg-white/5 px-4 py-2 text-sm text-white shadow hover:bg-white/10 cursor-pointer flex items-center gap-2 disabled:opacity-50"
        >
          <IconRefresh className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
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
    </div>
  );
}
