'use client';

import { useEffect, useState, useMemo } from "react";
import { chatApi, Conversation } from "@/lib/chat/api";
import Info from "@/components/ui/info";
import { MdDelete, MdChat } from "react-icons/md";
import { Modal, Button, Group, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useNotification } from "@/contexts/notification-context";
import { useAuth } from "@/components/auth/auth-provider";
import { useRouter } from "next/navigation";

const header = ["ID", "Name", "Created", "Last Modified"];

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [opened, { open, close }] = useDisclosure(false);
  const [deletingConversation, setDeletingConversation] = useState<Conversation | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  
  const { error: notifyError, success: notifySuccess } = useNotification();
  const { user } = useAuth();
  const router = useRouter();

  const loadConversations = async () => {
    try {
      setIsLoading(true);
      const result = await chatApi.getConversations();
      if (result.ok && result.data) {
        setConversations(result.data);
      } else {
        notifyError(result.error || "Failed to load conversations");
      }
    } catch (e) {
      notifyError("Failed to load conversations");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadConversations();
  }, []);

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  const filteredConversations = useMemo(() => {
    return conversations.filter((c) => {
      const text = `${c.name ?? ""} ${c.id}`.toLowerCase();
      return text.includes(searchTerm.toLowerCase());
    });
  }, [conversations, searchTerm]);

  const tableBody: (string | number)[][] = filteredConversations.map((c) => [
    c.id,
    c.name,
    formatDate(c.created_at),
    formatDate(c.modified_at),
  ]);

  const canDelete = (conversation: Conversation) => {
    if (!user) return false;
    // Owner can delete their own conversations
    if (conversation.owner_username === user.username) return true;
    // Admin and Manager can delete any conversation
    if (user.role === 'admin' || user.role === 'manager') return true;
    return false;
  };

  const handleDeleteClick = (rowIndex: number) => {
    const conversation = filteredConversations[rowIndex];
    if (!conversation) return;
    
    if (!canDelete(conversation)) {
      notifyError("You don't have permission to delete this conversation");
      return;
    }
    
    setDeletingConversation(conversation);
    open();
  };

  const handleConfirmDelete = async () => {
    if (!deletingConversation) return;
    
    try {
      setIsDeleting(true);
      const result = await chatApi.deleteConversation(deletingConversation.id);
      
      if (result.ok) {
        setConversations((prev) => prev.filter((c) => c.id !== deletingConversation.id));
        notifySuccess("Conversation deleted successfully");
        close();
      } else {
        notifyError(result.error || "Failed to delete conversation");
      }
    } catch (e) {
      notifyError("Failed to delete conversation");
    } finally {
      setIsDeleting(false);
      setDeletingConversation(null);
    }
  };

  const handleOpenChat = (rowIndex: number) => {
    const conversation = filteredConversations[rowIndex];
    if (!conversation) return;
    router.push(`/chat?conversation=${conversation.id}`);
  };

  const handleRefresh = () => {
    loadConversations();
  };

  const actions = [
    {
      icon: <MdChat className="w-5 h-5" />,
      ariaLabel: "Open chat",
      onClick: handleOpenChat,
    },
    {
      icon: <MdDelete className="w-5 h-5" />,
      ariaLabel: "Delete conversation",
      onClick: handleDeleteClick,
    },
  ];

  return (
    <div className="space-y-4 p-4 md:p-6">
      <Modal
        opened={opened}
        onClose={close}
        title={<span className="font-semibold text-[var(--text)] text-lg">Delete Conversation</span>}
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
            Are you sure you want to <span className="text-red-500 underline">permanently</span> delete the conversation{' '}
            <span className="text-[var(--text)] font-bold">"{deletingConversation?.name}"</span>?
          </Text>
          <Text size="sm" className="text-[var(--textSoft)]">
            This action <span className="text-red-500 underline">cannot</span> be undone. All messages in this conversation will be lost.
          </Text>

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={close}
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
              Delete Conversation
            </Button>
          </Group>
        </div>
      </Modal>

      {isLoading ? (
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 text-[var(--textSoft)]">
          Loading conversations...
        </div>
      ) : (
        <Info
          title="Conversations"
          header={header}
          body={tableBody}
          actions={actions}
          button="↻"
          onButton={handleRefresh}
          searchConfig={{
            placeholder: "Search by name or ID...",
            value: searchTerm,
            onChange: setSearchTerm,
          }}
        />
      )}
    </div>
  );
}
