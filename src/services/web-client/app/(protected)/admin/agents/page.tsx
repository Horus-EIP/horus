'use client';

import { useCallback, useEffect, useState, useMemo } from "react";
import { agentApi, Agent, RegisterAgentPayload } from "@/lib/agents/api";
import Info from "@/components/ui/info";
import { IconPlus, IconTrash, IconKey } from "@tabler/icons-react";
import { Modal, Button, Group, Text, TextInput, Textarea, TagsInput } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useNotification } from "@/contexts/notification-context";
import { useAuth } from "@/components/auth/auth-provider";
import { AgentTypeBadge, getRole } from "@/components/agents/agent-type-badge";

const header = ["Name", "Role", "Description", "Status", "Last Heartbeat"];

export default function AdminAgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  
  // Delete modal
  const [deleteOpened, { open: openDelete, close: closeDelete }] = useDisclosure(false);
  const [deletingAgent, setDeletingAgent] = useState<Agent | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  
  // Register modal
  const [registerOpened, { open: openRegister, close: closeRegister }] = useDisclosure(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [newAgent, setNewAgent] = useState<RegisterAgentPayload>({
    name: "",
    skills: [],
    description: "",
  });
  const [registeredApiKey, setRegisteredApiKey] = useState<string | null>(null);

  // Regenerate API key modal
  const [regenOpened, { open: openRegen, close: closeRegen }] = useDisclosure(false);
  const [regeneratingAgent, setRegeneratingAgent] = useState<Agent | null>(null);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regeneratedApiKey, setRegeneratedApiKey] = useState<string | null>(null);

  const { error: notifyError, success: notifySuccess } = useNotification();
  const { user } = useAuth();

  const loadAgents = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await agentApi.getAgents();
      if (result.ok && result.data) {
        setAgents(result.data);
      } else {
        notifyError(result.error || "Failed to load agents");
      }
    } catch {
      notifyError("Failed to load agents");
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  const formatDate = (dateString: string) => {
    if (!dateString) return "Never";
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 5) return "Just now";
    if (diffMins < 60) return `${diffMins} min ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)} hours ago`;
    return date.toLocaleDateString();
  };

  const filteredAgents = useMemo(() => {
    return agents.filter((a) => {
      const text = `${a.name ?? ""} ${a.skills?.join(" ") ?? ""} ${a.description ?? ""}`.toLowerCase();
      return text.includes(searchTerm.toLowerCase());
    });
  }, [agents, searchTerm]);

  const tableBody: (string | number | React.ReactNode)[][] = filteredAgents.map((a) => {
    const role = getRole(a.skills ?? []);
    return [
      a.name,
      <AgentTypeBadge key={a.id || a.name} role={role} />,
      a.description || "-",
      a.status === 'active' ? 'Online' : 'Offline',
      formatDate(a.last_heartbeat),
    ];
  });

  const canManageAgents = () => {
    return user?.role === 'admin';
  };

  const handleDeleteClick = (rowIndex: number) => {
    const agent = filteredAgents[rowIndex];
    if (!agent) return;
    
    if (!canManageAgents()) {
      notifyError("Only admins can delete agents");
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
    } catch {
      notifyError("Failed to delete agent");
    } finally {
      setIsDeleting(false);
      setDeletingAgent(null);
    }
  };

  const handleRegisterAgent = async () => {
    if (!newAgent.name.trim()) {
      notifyError("Agent name is required");
      return;
    }
    if (newAgent.skills.length === 0) {
      notifyError("At least one skill is required");
      return;
    }
    if (!newAgent.description.trim()) {
      notifyError("Description is required");
      return;
    }
    
    try {
      setIsRegistering(true);
      const result = await agentApi.registerAgent(newAgent);
      
      if (result.ok && result.data) {
        notifySuccess("Agent registered successfully");
        setRegisteredApiKey(result.data.api_key);
        await loadAgents();
      } else {
        notifyError(result.error || "Failed to register agent");
      }
    } catch {
      notifyError("Failed to register agent");
    } finally {
      setIsRegistering(false);
    }
  };

  const handleCloseRegister = () => {
    setNewAgent({ name: "", skills: [], description: "" });
    setRegisteredApiKey(null);
    closeRegister();
  };

  const handleRegenerateClick = (rowIndex: number) => {
    const agent = filteredAgents[rowIndex];
    if (!agent) return;

    if (!canManageAgents()) {
      notifyError("Only admins can regenerate API keys");
      return;
    }

    setRegeneratingAgent(agent);
    setRegeneratedApiKey(null);
    openRegen();
  };

  const handleConfirmRegenerate = async () => {
    if (!regeneratingAgent) return;

    try {
      setIsRegenerating(true);
      const result = await agentApi.regenerateApiKey(regeneratingAgent.id);

      if (result.ok && result.data) {
        setRegeneratedApiKey(result.data.api_key);
        notifySuccess("API key regenerated successfully");
      } else {
        notifyError(result.error || "Failed to regenerate API key");
      }
    } catch {
      notifyError("Failed to regenerate API key");
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleCloseRegen = () => {
    setRegeneratingAgent(null);
    setRegeneratedApiKey(null);
    closeRegen();
  };

  const handleRefresh = () => {
    loadAgents();
  };

  const actions = canManageAgents() ? [
    {
      icon: <IconKey className="w-5 h-5" stroke={1.25} />,
      ariaLabel: "Regenerate API key",
      onClick: handleRegenerateClick,
    },
    {
      icon: <IconTrash className="w-5 h-5" stroke={1.25} />,
      ariaLabel: "Delete agent",
      onClick: handleDeleteClick,
    },
  ] : [];

  return (
    <div className="space-y-4 p-4 md:p-6">
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
            <span className="text-[var(--text)] font-bold">&quot;{deletingAgent?.name}&quot;</span>?
          </Text>
          <Text size="sm" className="text-[var(--textSoft)]">
            This action <span className="text-red-500 underline">cannot</span> be undone. The agent will no longer receive tasks.
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

      {/* Register Modal */}
      <Modal
        opened={registerOpened}
        onClose={handleCloseRegister}
        title={<span className="font-semibold text-[var(--text)] text-lg">
          {registeredApiKey ? "Agent Registered Successfully" : "Register New Agent"}
        </span>}
        centered
        size="lg"
        styles={{
          content: { backgroundColor: 'var(--bgSoft)', border: '1px solid rgba(255,255,255,0.1)' },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        {registeredApiKey ? (
          <div className="flex flex-col gap-4">
            <div className="p-4 bg-green-900/20 border border-green-500/30 rounded-lg">
              <Text size="sm" className="text-green-400 font-medium mb-2">
                Agent registered successfully! Save the API key below - it won&apos;t be shown again.
              </Text>
              <div className="bg-black/30 p-3 rounded-md">
                <code className="text-xs text-[var(--text)] break-all">{registeredApiKey}</code>
              </div>
            </div>
            <Button
              onClick={handleCloseRegister}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              Close
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <TextInput
              label="Agent Name"
              placeholder="e.g., DocumentAnalyzer"
              value={newAgent.name}
              onChange={(e) => setNewAgent({ ...newAgent, name: e.target.value })}
              required
              classNames={{
                input: "bg-[var(--bg)] text-[var(--text)] border-white/10",
                label: "text-[var(--text)]",
              }}
            />
            
            <TagsInput
              label="Skills"
              placeholder="Type a skill and press Enter"
              value={newAgent.skills}
              onChange={(value) => setNewAgent({ ...newAgent, skills: value })}
              required
              classNames={{
                input: "bg-[var(--bg)] text-[var(--text)] border-white/10",
                label: "text-[var(--text)]",
                pill: "bg-blue-600 text-white",
              }}
            />
            <Text size="xs" className="text-[var(--textSoft)] -mt-2">
              Examples: nlp, summarization, document_analysis, code_review
            </Text>
            
            <Textarea
              label="Description"
              placeholder="Describe what this agent does..."
              value={newAgent.description}
              onChange={(e) => setNewAgent({ ...newAgent, description: e.target.value })}
              required
              minRows={3}
              classNames={{
                input: "bg-[var(--bg)] text-[var(--text)] border-white/10",
                label: "text-[var(--text)]",
              }}
            />

            <Group justify="flex-end" mt="md">
              <Button
                variant="default"
                onClick={handleCloseRegister}
                disabled={isRegistering}
                className="bg-white/5 hover:bg-white/10 border-white/10 text-[var(--text)]"
              >
                Cancel
              </Button>
              <Button
                onClick={handleRegisterAgent}
                loading={isRegistering}
                className="bg-blue-600 hover:bg-blue-700 text-white"
              >
                Register Agent
              </Button>
            </Group>
          </div>
        )}
      </Modal>

      {/* Regenerate API Key Modal */}
      <Modal
        opened={regenOpened}
        onClose={handleCloseRegen}
        title={<span className="font-semibold text-[var(--text)] text-lg">
          {regeneratedApiKey ? "New API Key Generated" : "Regenerate API Key"}
        </span>}
        centered
        size="lg"
        styles={{
          content: { backgroundColor: 'var(--bgSoft)', border: '1px solid rgba(255,255,255,0.1)' },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        {regeneratedApiKey ? (
          <div className="flex flex-col gap-4">
            <div className="p-4 bg-green-900/20 border border-green-500/30 rounded-lg">
              <Text size="sm" className="text-green-400 font-medium mb-2">
                New API key for &quot;{regeneratingAgent?.name}&quot;. Save it now - it won&apos;t be shown again.
              </Text>
              <div className="bg-black/30 p-3 rounded-md">
                <code className="text-xs text-[var(--text)] break-all">{regeneratedApiKey}</code>
              </div>
            </div>
            <Text size="xs" className="text-[var(--textSoft)]">
              The previous key no longer works. Update the agent with this key so it can keep sending heartbeats.
            </Text>
            <Button
              onClick={handleCloseRegen}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              Close
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <Text size="md" className="text-[var(--textSoft)]">
              Generate a new API key for{' '}
              <span className="text-[var(--text)] font-bold">&quot;{regeneratingAgent?.name}&quot;</span>?
            </Text>
            <Text size="sm" className="text-[var(--textSoft)]">
              The current key will <span className="text-red-500 underline">stop working immediately</span>. The agent must be reconfigured with the new key to keep sending heartbeats.
            </Text>

            <Group justify="flex-end" mt="md">
              <Button
                variant="default"
                onClick={handleCloseRegen}
                disabled={isRegenerating}
                className="bg-white/5 hover:bg-white/10 border-white/10 text-[var(--text)]"
              >
                Cancel
              </Button>
              <Button
                onClick={handleConfirmRegenerate}
                loading={isRegenerating}
                className="bg-blue-600 hover:bg-blue-700 text-white"
              >
                Regenerate Key
              </Button>
            </Group>
          </div>
        )}
      </Modal>

      {isLoading ? (
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 text-[var(--textSoft)]">
          Loading agents...
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {canManageAgents() && (
            <button
              onClick={openRegister}
              className="rounded-xl bg-blue-600 px-4 py-2 text-sm text-white shadow hover:bg-blue-700 cursor-pointer w-fit self-end flex items-center gap-2"
            >
              <IconPlus className="w-5 h-5" stroke={1.25} />
              Register Agent
            </button>
          )}
          <Info
            title="Agents Management"
            header={header}
            body={tableBody}
            actions={actions}
            button="↻"
            onButton={handleRefresh}
            searchConfig={{
              placeholder: "Search by name, skills, or description...",
              value: searchTerm,
              onChange: setSearchTerm,
            }}
          />
        </div>
      )}
    </div>
  );
}
