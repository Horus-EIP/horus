'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Button,
  Group,
  Loader,
  Radio,
  Select,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { IconRobot, IconArrowLeft } from '@tabler/icons-react';
import { agentApi, type Agent } from '@/lib/agents/api';
import { chatApi, type Conversation } from '@/lib/chat/api';
import { useNotification } from '@/contexts/notification-context';
import type { TaskMode } from '@/lib/types';

type SkillOption = { value: string; label: string };

function uniqueSkills(agents: Agent[]): SkillOption[] {
  const seen = new Set<string>();
  agents.forEach((a) => (a.skills || []).forEach((s) => seen.add(s)));
  return Array.from(seen)
    .sort((a, b) => a.localeCompare(b))
    .map((s) => ({ value: s, label: s.replace(/_/g, ' ') }));
}

function formatAgentLabel(a: Agent): string {
  const status = a.status === 'active' ? '🟢' : '⚪';
  return `${status} ${a.name}`;
}

export default function NewTaskPage() {
  const router = useRouter();
  const { error: notifyError, success: notifySuccess } = useNotification();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);

  const [demand, setDemand] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [mode, setMode] = useState<TaskMode>('auto');
  const [skill, setSkill] = useState<string | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [a, c] = await Promise.all([
        agentApi.getAgents(),
        chatApi.getConversations(),
      ]);
      if (cancelled) return;
      if (a.ok && a.data) setAgents(a.data);
      else notifyError(a.error || 'Failed to load agents');
      if (c.ok && c.data) setConversations(c.data);
      else notifyError(c.error || 'Failed to load conversations');
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [notifyError]);

  const skillOptions = useMemo(() => uniqueSkills(agents), [agents]);

  const filteredAgents = useMemo(() => {
    if (!skill) return agents;
    return agents.filter((a) => (a.skills || []).includes(skill));
  }, [agents, skill]);

  const agentOptions = useMemo(
    () =>
      filteredAgents.map((a) => ({
        value: a.id,
        label: formatAgentLabel(a),
      })),
    [filteredAgents]
  );

  const conversationOptions = useMemo(
    () =>
      conversations.map((c) => ({
        value: String(c.id),
        label: c.name || `Conversation ${c.id}`,
      })),
    [conversations]
  );

  // If the user changes the skill filter, drop a now-invalid agent selection.
  useEffect(() => {
    if (!agentId) return;
    const stillValid = filteredAgents.some((a) => a.id === agentId);
    if (!stillValid) setAgentId(null);
  }, [skill, filteredAgents, agentId]);

  const validate = (): string | null => {
    if (!demand.trim()) return 'Please describe the task.';
    if (!conversationId) return 'Pick a conversation to attach the task to.';
    if (mode === 'specific_agent' && !agentId)
      return 'Specific-agent mode requires you to pick an agent.';
    if (mode === 'any_with_skill' && !skill)
      return 'Skill-based mode requires you to pick a skill.';
    return null;
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) {
      notifyError(err);
      return;
    }

    setSubmitting(true);
    try {
      const skillsRequired = skill ? [skill] : [];
      const result = await chatApi.createTask({
        demand: demand.trim(),
        conversation_id: conversationId!,
        skills_required: skillsRequired,
        mode,
        agent_id: mode === 'specific_agent' ? agentId! : undefined,
      });

      if (!result.ok) {
        notifyError(result.error || 'Failed to dispatch task');
        return;
      }

      notifySuccess('Task dispatched.');
      // Navigate the user to the chat for that conversation so they see the
      // attribution chip + WS task_complete event live.
      router.push(`/chat?conversation=${conversationId}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <button
        type="button"
        onClick={() => router.back()}
        className="mb-4 inline-flex items-center gap-2 text-sm text-[var(--textSoft)] hover:text-[var(--text)]"
      >
        <IconArrowLeft className="h-4 w-4" /> Back
      </button>

      <h1 className="mb-1 flex items-center gap-2 text-xl font-bold text-[var(--text)]">
        <IconRobot className="h-6 w-6 text-blue-500" stroke={1.25} />
        New Task
      </h1>
      <Text size="sm" className="mb-6 text-[var(--textSoft)]">
        Describe the work, choose how it should be routed, and dispatch.
      </Text>

      <Stack gap="md">
        <Textarea
          label="What do you need?"
          placeholder="Summarise the Q4 financial risks..."
          value={demand}
          onChange={(e) => setDemand(e.currentTarget.value)}
          minRows={4}
          autosize
          maxLength={2000}
          required
        />

        <Select
          label="Conversation"
          placeholder="Pick a conversation..."
          data={conversationOptions}
          value={conversationId}
          onChange={setConversationId}
          searchable
          required
          nothingFoundMessage="No conversations yet — create one from the chat page first."
        />

        <Radio.Group
          label="Routing mode"
          value={mode}
          onChange={(v) => setMode(v as TaskMode)}
          required
        >
          <Stack gap="xs" mt="xs">
            <Radio
              value="auto"
              label="Auto — let the orchestrator pick the best agent"
            />
            <Radio
              value="any_with_skill"
              label="Any agent with a specific skill"
            />
            <Radio
              value="specific_agent"
              label="Specific agent (queue-on-busy if offline)"
            />
          </Stack>
        </Radio.Group>

        <Tooltip
          label="Skill is optional in Auto mode and required in Skill / Specific modes."
          position="top-start"
          openDelay={500}
        >
          <Select
            label="Skill"
            placeholder={skillOptions.length ? 'Pick a skill...' : 'No skills advertised yet'}
            data={skillOptions}
            value={skill}
            onChange={setSkill}
            searchable
            clearable
            disabled={!skillOptions.length}
            description={
              mode === 'auto'
                ? 'Optional in Auto mode — passed as a hint to the router.'
                : 'Required.'
            }
          />
        </Tooltip>

        <Select
          label="Agent"
          placeholder={
            mode === 'specific_agent'
              ? 'Pick the agent to assign...'
              : 'Auto-selected'
          }
          data={agentOptions}
          value={agentId}
          onChange={setAgentId}
          searchable
          clearable
          disabled={mode !== 'specific_agent'}
          description={
            skill
              ? `Filtered by skill: ${skill}`
              : 'Showing every registered agent.'
          }
        />

        <Group justify="flex-end" mt="md">
          <Button
            variant="default"
            onClick={() => router.back()}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            loading={submitting}
            className="bg-blue-600 text-white hover:bg-blue-700"
          >
            Dispatch task
          </Button>
        </Group>
      </Stack>
    </div>
  );
}
