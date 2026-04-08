'use client';

import { useCallback, useEffect, useState, useRef } from "react";
import Card from "@/components/ui/card";
import Info from "@/components/ui/info";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/auth/auth-provider";
import { agentApi, Agent as AgentType } from "@/lib/agents/api";
import { chatApi, TaskQueueStats } from "@/lib/chat/api";
import { useNotification } from "@/contexts/notification-context";
import { IconTrash } from "@tabler/icons-react";
import { Modal, Button, Group, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';

interface Agent {
  id: string;
  name: string;
  lastActive: string;
  skills: string;
  status: string;
}

// System metrics for the real-time graph
interface SystemMetric {
  timestamp: number;
  activeAgents: number;
  runningTasks: number;
  pendingTasks: number;
}

const MAX_DATA_POINTS = 30;

export default function DashboardPage() {
  const { status, user } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [rawAgents, setRawAgents] = useState<AgentType[]>([]);
  const [taskStats, setTaskStats] = useState<TaskQueueStats | null>(null);
  const [metrics, setMetrics] = useState<SystemMetric[]>([]);
  
  // Delete modal
  const [deleteOpened, { open: openDelete, close: closeDelete }] = useDisclosure(false);
  const [deletingAgent, setDeletingAgent] = useState<Agent | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  
  const { error: notifyError, success: notifySuccess } = useNotification();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const agentHeaders: string[] = [
    "Agent",
    "Last active",
    "Skills",
    "Status"
  ];

  const timeAgo = useCallback((date: string) => {
    if (!date) return "Never";
    const now = new Date();
    const past = new Date(date);
    const diff = now.getTime() - past.getTime();
    const minutes = Math.floor(diff / 60000);

    return minutes < 5 ? 'A few minutes ago' : minutes < 60 ? `${minutes} minutes ago` : `${Math.floor(minutes / 60)} hours ago`;
  }, []);

  const getAgents = useCallback(async () => {
    const result = await agentApi.getAgents();
    
    if (result.ok && result.data) {
      setRawAgents(result.data);
      const list: Agent[] = result.data.map((info) => ({
        id: info.id,
        name: info.name,
        lastActive: timeAgo(info.last_heartbeat),
        skills: Array.isArray(info.skills)
          ? info.skills.join(', ').replace(/_/g, ' ')
          : '-',
        status:
          info.status === 'active'
            ? 'Online'
            : (info.status || '-')
              .toString()
              .charAt(0)
              .toUpperCase() + (info.status || '-')
                .toString()
                .slice(1),
      }));
      setAgents(list);
    }
  }, [timeAgo]);

  const getTaskStats = useCallback(async () => {
    const result = await chatApi.getTaskQueueStats();
    if (result.ok && result.data) {
      setTaskStats(result.data);
    }
  }, []);

  // Update metrics for the graph
  const updateMetrics = useCallback(() => {
    const activeAgentsCount = agents.filter(a => a.status === 'Online').length;
    const runningTasksCount = taskStats?.running || 0;
    const pendingTasksCount = taskStats?.pending || 0;

    setMetrics(prev => {
      const newMetric: SystemMetric = {
        timestamp: Date.now(),
        activeAgents: activeAgentsCount,
        runningTasks: runningTasksCount,
        pendingTasks: pendingTasksCount,
      };
      
      const updated = [...prev, newMetric];
      if (updated.length > MAX_DATA_POINTS) {
        return updated.slice(-MAX_DATA_POINTS);
      }
      return updated;
    });
  }, [agents, taskStats]);

  // Draw the graph
  const drawGraph = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * window.devicePixelRatio;
    canvas.height = rect.height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    const width = rect.width;
    const height = rect.height;
    const padding = 40;
    const graphWidth = width - padding * 2;
    const graphHeight = height - padding * 2;

    // Clear canvas
    ctx.fillStyle = 'rgba(30, 30, 40, 0.5)';
    ctx.fillRect(0, 0, width, height);

    if (metrics.length < 2) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Collecting data...', width / 2, height / 2);
      return;
    }

    // Find max values for scaling
    const maxActiveAgents = Math.max(...metrics.map(m => m.activeAgents), 1);
    const maxRunningTasks = Math.max(...metrics.map(m => m.runningTasks), 1);
    const maxPendingTasks = Math.max(...metrics.map(m => m.pendingTasks), 1);
    const maxValue = Math.max(maxActiveAgents, maxRunningTasks, maxPendingTasks, 5);

    // Draw grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
      const y = padding + (graphHeight / 5) * i;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.stroke();

      // Y-axis labels
      ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'right';
      const value = Math.round(maxValue - (maxValue / 5) * i);
      ctx.fillText(value.toString(), padding - 5, y + 3);
    }

    // Draw lines helper
    const drawLine = (data: number[], color: string, label: string, yOffset: number) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      
      data.forEach((value, index) => {
        const x = padding + (graphWidth / (data.length - 1)) * index;
        const y = padding + graphHeight - (value / maxValue) * graphHeight;
        
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();

      // Legend
      ctx.fillStyle = color;
      ctx.fillRect(padding + 10, height - 20 + yOffset, 20, 3);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(label, padding + 35, height - 17 + yOffset);
    };

    // Draw the lines
    drawLine(metrics.map(m => m.activeAgents), '#22c55e', 'Active Agents', -30);
    drawLine(metrics.map(m => m.runningTasks), '#3b82f6', 'Running Tasks', -15);
    drawLine(metrics.map(m => m.pendingTasks), '#eab308', 'Pending Tasks', 0);

    // Title
    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('System Activity (Real-time)', padding, 20);
  }, [metrics]);

  useEffect(() => {
    if (status === 'authenticated') {
      getAgents();
      getTaskStats();
    }
  }, [getAgents, getTaskStats, status]);

  // Refresh data periodically
  useEffect(() => {
    if (status !== 'authenticated') return;
    
    const interval = setInterval(() => {
      getAgents();
      getTaskStats();
    }, 10000); // Refresh every 10 seconds

    return () => clearInterval(interval);
  }, [getAgents, getTaskStats, status]);

  // Update metrics when data changes
  useEffect(() => {
    updateMetrics();
  }, [updateMetrics]);

  // Redraw graph when metrics change
  useEffect(() => {
    drawGraph();
  }, [drawGraph]);

  // Handle window resize
  useEffect(() => {
    const handleResize = () => drawGraph();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [drawGraph]);

  const canManageAgents = () => {
    return user?.role === 'admin' || user?.role === 'manager';
  };

  const handleDeleteClick = (rowIndex: number) => {
    const agent = agents[rowIndex];
    if (!agent) return;
    
    if (!canManageAgents()) {
      notifyError("You don't have permission to delete agents");
      return;
    }
    
    setDeletingAgent(agent);
    openDelete();
  };

  const handleConfirmDelete = async () => {
    if (!deletingAgent) return;
    
    try {
      setIsDeleting(true);
      const result = await agentApi.deleteAgent(deletingAgent.id);
      
      if (result.ok) {
        setAgents((prev) => prev.filter((a) => a.id !== deletingAgent.id));
        notifySuccess("Agent deleted successfully");
        closeDelete();
      } else {
        notifyError(result.error || "Failed to delete agent");
      }
    } catch (e) {
      notifyError("Failed to delete agent");
    } finally {
      setIsDeleting(false);
      setDeletingAgent(null);
    }
  };

  const actions = canManageAgents() ? [
    {
      icon: <IconTrash className="w-5 h-5" stroke={1.25} />,
      ariaLabel: "Delete agent",
      onClick: handleDeleteClick,
    },
  ] : undefined;

  const tableBody = agents.map((agent) => [
    agent.name,
    agent.lastActive,
    agent.skills,
    agent.status
  ]);

  return (
    <div className="flex gap-3 mt-5 p-0">
      {/* Delete Modal */}
      <Modal
        opened={deleteOpened}
        onClose={closeDelete}
        title={<span className="font-semibold text-[var(--text)] text-lg">Delete Agent</span>}
        centered
        styles={{
          content: { backgroundColor: 'var(--bgSoft)', border: '1px solid rgba(255,255,255,0.1)' },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        <div className="flex flex-col gap-4">
          <Text size="md" className="text-[var(--textSoft)]">
            Are you sure you want to <span className="text-red-500 underline">permanently</span> delete the agent{' '}
            <span className="text-[var(--text)] font-bold">"{deletingAgent?.name}"</span>?
          </Text>
          <Text size="sm" className="text-[var(--textSoft)]">
            This action <span className="text-red-500 underline">cannot</span> be undone.
          </Text>

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={closeDelete}
              disabled={isDeleting}
              className="bg-white/5 hover:bg-white/10 border-white/10 text-[var(--text)]"
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirmDelete}
              loading={isDeleting}
              color="red"
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              Delete Agent
            </Button>
          </Group>
        </div>
      </Modal>

      <div className="flex-3 flex flex-col gap-5 p-0 w-full">
        {/* Real-time Analytics Graph */}
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 mx-3">
          <canvas
            ref={canvasRef}
            className="w-full h-48 rounded-lg"
            style={{ maxWidth: '100%' }}
          />
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-5 px-3 w-full justify-items-center md:justify-items-stretch">
          <Card
            title="Active Agents"
            number={agents.filter((agent) => agent.status === 'Online').length}
          />
          <Card
            title="Running Tasks"
            number={taskStats?.running || 0}
          />
          <Card
            title="Pending Tasks"
            number={taskStats?.pending || 0}
          />
          <Card
            title="Completed Tasks"
            number={taskStats?.completed || 0}
          />
        </div>

        {/* Agent Status Table */}
        <div className="overflow-x-auto px-0 md:px-0 w-full max-w-[75vw] md:max-w-full mx-auto">
          <Info
            title="Agent Status"
            header={agentHeaders}
            body={tableBody}
            actions={actions}
          />
        </div>
      </div>
    </div>
  )
}
