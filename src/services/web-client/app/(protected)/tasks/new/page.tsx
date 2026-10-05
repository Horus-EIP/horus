'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Badge,
  Button,
  Group,
  Loader,
  MultiSelect,
  Radio,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { IconRobot, IconArrowLeft, IconSparkles } from '@tabler/icons-react';
import { agentApi, type Agent } from '@/lib/agents/api';
import { chatApi, type SuggestedSkill } from '@/lib/chat/api';
import { useNotification } from '@/contexts/notification-context';
import type { TaskMode } from '@/lib/types';
import {
  FileAttachments,
  type FileAttachmentsValue,
} from '@/components/tasks/file-attachments';

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
  const [loading, setLoading] = useState(true);

  const MAX_SKILLS = 5;

  const [demand, setDemand] = useState('');
  const [mode, setMode] = useState<TaskMode>('auto');
  const [autoDetectSkills, setAutoDetectSkills] = useState(true);
  const [skills, setSkills] = useState<string[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // First skill the user picked, used to filter agents in specific_agent mode.
  const skill = skills[0] ?? null;

  const [suggestions, setSuggestions] = useState<SuggestedSkill[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const suggestRequestId = useRef(0);

  const [attachments, setAttachments] = useState<FileAttachmentsValue>({
    attached: [],
    inline: [],
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const a = await agentApi.getAgents();
      if (cancelled) return;
      if (a.ok && a.data) setAgents(a.data);
      else notifyError(a.error || 'Failed to load agents');
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

  // If the user changes the skill filter, drop a now-invalid agent selection.
  useEffect(() => {
    if (!agentId) return;
    const stillValid = filteredAgents.some((a) => a.id === agentId);
    if (!stillValid) setAgentId(null);
  }, [skill, filteredAgents, agentId]);

  // Debounced skill suggestions. Fires 400ms after the user stops typing,
  // only once the demand is long enough to be meaningful. A request-id guard
  // makes sure a stale response can't overwrite a fresher one.
  useEffect(() => {
    const trimmed = demand.trim();
    if (trimmed.length < 12) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }
    const myId = ++suggestRequestId.current;
    setSuggestionsLoading(true);
    const handle = window.setTimeout(async () => {
      const result = await chatApi.suggestSkills(trimmed, 3);
      if (myId !== suggestRequestId.current) return;
      setSuggestionsLoading(false);
      if (result.ok && result.data) setSuggestions(result.data);
      else setSuggestions([]);
    }, 400);
    return () => window.clearTimeout(handle);
  }, [demand]);

  const validate = (): string | null => {
    if (!demand.trim()) return 'Please describe the task.';
    if (mode === 'specific_agent' && !agentId)
      return 'Specific-agent mode requires you to pick an agent.';
    if (mode === 'any_with_skill' && !autoDetectSkills && skills.length === 0)
      return 'Skill-based mode requires at least one skill (or enable auto-detect).';
    if (skills.length > MAX_SKILLS)
      return `Pick at most ${MAX_SKILLS} skills — more than that just noises up the router.`;
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
      // Auto-detect → send no skills so the orchestrator's router picks. Otherwise
      // forward every skill the user selected so routing has more to work with.
      const skillsRequired = autoDetectSkills ? [] : skills;
      const result = await chatApi.createTask({
        demand: demand.trim(),
        skills_required: skillsRequired,
        mode,
        agent_id: mode === 'specific_agent' ? agentId! : undefined,
        attached_files: attachments.attached,
        inline_files: attachments.inline,
      });

      const taskId = result.ok ? result.data?.task_id : undefined;
      if (!taskId) {
        notifyError(result.error || 'Failed to dispatch task');
        router.push('/tasks');
        return;
      }

      notifySuccess('Task queued. Routing runs in the background.');
      router.push(`/tasks/${taskId}`);
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
            <Radio
              value="decompose"
              label="Force decomposition — split across multiple specialists"
            />
          </Stack>
        </Radio.Group>

        <div>
          <Switch
            label="Auto-detect skills"
            description="Let the orchestrator pick which skill(s) this task needs. Turn off to choose them yourself."
            checked={autoDetectSkills}
            onChange={(e) => {
              setAutoDetectSkills(e.currentTarget.checked);
              if (e.currentTarget.checked) setSkills([]);
            }}
            mb="xs"
          />
          <Tooltip
            label={`Pick 1–${MAX_SKILLS} skills. More tags don't help — the router just gets noisier.`}
            position="top-start"
            openDelay={500}
          >
            <MultiSelect
              label="Skills"
              placeholder={
                autoDetectSkills
                  ? 'Auto-detect is on — orchestrator picks'
                  : skillOptions.length
                    ? 'Pick up to 5 skills…'
                    : 'No skills advertised yet'
              }
              data={skillOptions}
              value={skills}
              onChange={(next) =>
                setSkills(next.slice(0, MAX_SKILLS))
              }
              searchable
              clearable
              disabled={autoDetectSkills || !skillOptions.length}
              maxValues={MAX_SKILLS}
              nothingFoundMessage="No matching skills"
              description={
                autoDetectSkills
                  ? 'Auto-detect is on. Disable it above to pick skills manually.'
                  : mode === 'auto'
                    ? 'Optional in Auto mode — forwarded to the router as hints.'
                    : 'Required for Skill / Specific-agent modes.'
              }
            />
          </Tooltip>

          {!autoDetectSkills && (suggestionsLoading || suggestions.length > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Group gap={4} align="center">
                <IconSparkles className="h-3.5 w-3.5 text-violet-400" />
                <Text size="xs" c="dimmed">
                  {suggestionsLoading ? 'Suggesting…' : 'Suggested:'}
                </Text>
              </Group>
              {suggestions.map((s) => {
                const active = skills.includes(s.skill);
                const onClick = () => {
                  if (active) {
                    setSkills(skills.filter((x) => x !== s.skill));
                  } else if (skills.length < MAX_SKILLS) {
                    setSkills([...skills, s.skill]);
                  }
                };
                return (
                  <Badge
                    key={`${s.skill}-${s.agent_id}`}
                    component="button"
                    type="button"
                    variant={active ? 'filled' : 'light'}
                    color={active ? 'violet' : 'gray'}
                    onClick={onClick}
                    style={{ cursor: 'pointer' }}
                    title={`Best match: ${s.agent_name} (score ${s.score.toFixed(2)})`}
                  >
                    {s.skill.replace(/_/g, ' ')}
                  </Badge>
                );
              })}
            </div>
          )}
        </div>

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

        <FileAttachments
          value={attachments}
          onChange={setAttachments}
          onError={notifyError}
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
