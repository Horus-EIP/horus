'use client';

import { useEffect, useMemo, useState } from "react";
import { userApi } from "@/lib/users/api";
import type { User, UserRole } from "@/lib/types";
import Info from "@/components/ui/info";
import { IconEdit, IconPlus, IconTrash } from "@tabler/icons-react";
import { Modal, Button, Group, Text, Select, TextInput, PasswordInput } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { useNotification } from "@/contexts/notification-context";
import { IconChevronDown } from "@tabler/icons-react";

type RoleFilter = "all" | UserRole;

const ROLES_OPTIONS = [
  { value: "all", label: "All roles" },
  { value: "admin", label: "Admin" },
  { value: "manager", label: "Manager" },
  { value: "user", label: "User" },
];

const header = ["ID", "Username", "Role"];

const AdminUsersPage = () => {
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");

  // Edit role modal
  const [opened, { open, close }] = useDisclosure(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [selectedRole, setSelectedRole] = useState<string>("user");
  const [isSaving, setIsSaving] = useState(false);
  
  // Create user modal
  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState<string>("user");
  const [isCreating, setIsCreating] = useState(false);
  
  const { error: notifyError, success: notifySuccess } = useNotification();

  const assignableRoles = useMemo(() => {
    return ROLES_OPTIONS.filter((r) => r.value !== "all");
  }, []);

  const loadUsers = async () => {
    try {
      setIsLoading(true);
      const list = await userApi.listUsers();
      setUsers(list);
    } catch (e) {
      notifyError("Failed to load users.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers();
  }, []);

  const filteredUsers = useMemo(() => {
    return users.filter((u) => {
      const text = `${u.username ?? ""}`.toLowerCase();
      const searchOk = text.includes(searchTerm.toLowerCase());
      const role = (u.role as UserRole | undefined) ?? "user";
      const roleOk = roleFilter === "all" || role === roleFilter;
      return searchOk && roleOk;
    });
  }, [users, searchTerm, roleFilter]);

  const tableBody: (string | number)[][] = filteredUsers.map((u) => [
    u.id,
    u.username,
    (u.role as UserRole | undefined) ?? "user",
  ]);

  const handleDeleteRow = async (rowIndex: number) => {
    const userToDelete = filteredUsers[rowIndex];
    if (!userToDelete) return;

    modals.openConfirmModal({
      title: <span className="font-semibold text-[var(--text)] text-lg">Delete User</span>,
      centered: true,
      children: (
        <Text size="md" p={6}>
          <p className="text-[var(--textSoft)] mb-4">
            Are you sure you want to <span className="text-red-500 underline">permanently</span> delete the user{' '}<span className="text-[var(--text)] font-bold">{userToDelete.username}</span>?
          </p>
          <p className="text-[var(--textSoft)]">This action <span className="text-red-500 underline">cannot</span> be undone.</p>
        </Text>
      ),
      labels: { confirm: 'Delete User', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      cancelProps: { variant: 'default', className: 'text-[var(--text)] bg-white/5 border-white/10 hover:bg-white/10' },

      overlayProps: {
        backgroundOpacity: 0.55,
        blur: 3,
      },
      styles: {
        content: { backgroundColor: 'var(--bgSoft)', border: '1px solid rgba(255,255,255,0.1)' },
        header: { backgroundColor: 'var(--bgSoft)' },
        body: { backgroundColor: 'var(--bgSoft)' },
        title: { color: 'var(--text)' },
      },

      onConfirm: async () => {
        const ok = await userApi.deleteUser(userToDelete.id);

        if (ok) {
          setUsers((prev) => prev.filter((u) => u.id !== userToDelete.id));
          notifySuccess("User deleted successfully.");
        } else {
          notifyError("Failed to delete user.");
        }
      },
    });
  };

  const handleRefresh = () => {
    void loadUsers();
  };

  const handleEditClick = (rowIndex: number) => {
    const user = filteredUsers[rowIndex];
    if (!user) return;
    setEditingUser(user);
    setSelectedRole(user.role || 'user');
    open();
  };

  const handleSaveRole = async () => {
    if (!editingUser || !selectedRole) return;
    try {
      setIsSaving(true);
      const ok = await userApi.updateRole({
        username: editingUser.username,
        newRole: selectedRole as UserRole
      });
      if (ok) {
        notifySuccess("User role updated successfully.");
      } else {
        notifyError("Failed to update user role.");
      }
      await loadUsers();
      close();
    } catch (error) {
      notifyError("Failed to update user role.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleCreateUser = async () => {
    if (!newUsername.trim()) {
      notifyError("Username is required");
      return;
    }
    if (!newPassword.trim() || newPassword.length < 6) {
      notifyError("Password must be at least 6 characters");
      return;
    }

    try {
      setIsCreating(true);
      const result = await userApi.createUser({
        username: newUsername.trim(),
        password: newPassword,
        role: newUserRole as UserRole,
      });

      if (result.ok) {
        if (result.error) {
          // User created but with a warning
          notifySuccess(`User "${newUsername}" created. ${result.error}`);
        } else {
          notifySuccess(`User "${newUsername}" created successfully.`);
        }
        await loadUsers();
        handleCloseCreate();
      } else {
        notifyError(result.error || "Failed to create user");
      }
    } catch (error) {
      notifyError("Failed to create user");
    } finally {
      setIsCreating(false);
    }
  };

  const handleCloseCreate = () => {
    setNewUsername("");
    setNewPassword("");
    setNewUserRole("user");
    closeCreate();
  };

  const actions = [
    {
      icon: <IconEdit className="w-5 h-5" stroke={1.25} />,
      ariaLabel: "Edit user role",
      onClick: handleEditClick,
    },
    {
      icon: <IconTrash className="w-5 h-5" stroke={1.25} />,
      ariaLabel: "Delete user",
      onClick: handleDeleteRow,
    },
  ];

  return (
    <div className="space-y-4 p-4 md:p-6">
      {/* Edit Role Modal */}
      <Modal
        opened={opened}
        onClose={close}
        title={<span className="font-semibold text-[var(--text)] text-lg">Edit User Role</span>}
        centered
        styles={{
          content: { backgroundColor: 'var(--bgSoft)', border: '1px solid rgba(255,255,255,0.1)' },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        <div className="flex flex-col gap-4">
          <p className="text-md text-[var(--textSoft)]">
            Changing role for user: <strong className="text-[var(--text)]">{editingUser?.username}</strong>
          </p>

          <div className="flex flex-col gap-2">
            <label className="text-md font-medium text-[var(--text)]">Select Role</label>

            <Select
              className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-[var(--text)] outline-none"
              value={selectedRole}
              data={assignableRoles}
              onChange={(value) => value && setSelectedRole(value)}
              rightSection={<IconChevronDown size={14} className="text-[var(--textSoft)]" />}

              classNames={{
                input: `
                  !bg-[var(--bg)] 
                  !text-[var(--text)]
                  rounded-xl
                  !border-none
                `,
                dropdown: `
                  !bg-[var(--bgSoft)]
                  !backdrop-blur-xl /* Efeito de vidro */
                  !border-white/10  /* Borda sutil */
                  !rounded-xl       /* Cantos arredondados no menu */
                  !shadow-2xl
                  p-1              /* Padding interno */
                `,
                option: `
                  !rounded-lg       /* Opções arredondadas */
                  !text-[var(--textSoft)]
                  !hover:bg-white/10 /* Hover bonito */
                  !hover:text-white
                  !data-[checked]:bg-blue-600 /* Item selecionado */
                  !data-[checked]:text-white
                  mb-1             /* Espacinho entre opções */
                `
              }}
              comboboxProps={{
                transitionProps: { transition: 'pop', duration: 200 },
                offset: 8
              }}
            />
          </div>

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={close}
              disabled={isSaving}
              className="bg-white/5 hover:bg-white/10 border-white/10 text-[var(--text)]"
            >
              Cancel
            </Button>
            <Button
              onClick={handleSaveRole}
              loading={isSaving}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              Save Changes
            </Button>
          </Group>
        </div>
      </Modal>

      {/* Create User Modal */}
      <Modal
        opened={createOpened}
        onClose={handleCloseCreate}
        title={<span className="font-semibold text-[var(--text)] text-lg">Create New User</span>}
        centered
        size="md"
        styles={{
          content: { backgroundColor: 'var(--bgSoft)', border: '1px solid rgba(255,255,255,0.1)' },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        <div className="flex flex-col gap-4">
          <TextInput
            label="Username"
            placeholder="Enter username"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            required
            classNames={{
              input: "bg-[var(--bg)] text-[var(--text)] border-white/10",
              label: "text-[var(--text)]",
            }}
          />
          
          <PasswordInput
            label="Password"
            placeholder="Enter password (min 6 characters)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={6}
            classNames={{
              input: "bg-[var(--bg)] text-[var(--text)] border-white/10",
              label: "text-[var(--text)]",
            }}
          />

          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-[var(--text)]">Role</label>
            <Select
              value={newUserRole}
              data={assignableRoles}
              onChange={(value) => value && setNewUserRole(value)}
              rightSection={<IconChevronDown size={14} className="text-[var(--textSoft)]" />}
              classNames={{
                input: "!bg-[var(--bg)] !text-[var(--text)] rounded-xl !border-none",
                dropdown: "!bg-[var(--bgSoft)] !backdrop-blur-xl !border-white/10 !rounded-xl !shadow-2xl p-1",
                option: "!rounded-lg !text-[var(--textSoft)] !hover:bg-white/10 !hover:text-white !data-[checked]:bg-blue-600 !data-[checked]:text-white mb-1"
              }}
              comboboxProps={{
                transitionProps: { transition: 'pop', duration: 200 },
                offset: 8
              }}
            />
          </div>

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={handleCloseCreate}
              disabled={isCreating}
              className="bg-white/5 hover:bg-white/10 border-white/10 text-[var(--text)]"
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateUser}
              loading={isCreating}
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              Create User
            </Button>
          </Group>
        </div>
      </Modal>

      {isLoading ? (
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 text-[var(--textSoft)]">
          Loading users…
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex gap-2 self-end flex-wrap justify-end">
            <button
              onClick={openCreate}
              className="rounded-xl bg-green-600 px-3 py-2 text-sm text-white shadow hover:bg-green-700 cursor-pointer flex items-center gap-2"
            >
              <IconPlus className="w-5 h-5" stroke={1.25} />
              Create User
            </button>
            <button
              onClick={() => window.location.href = '/admin/agents'}
              className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white shadow hover:bg-blue-700 cursor-pointer"
            >
              Manage Agents
            </button>
            <button
              onClick={() => window.location.href = '/admin/roles'}
              className="rounded-xl bg-white/5 px-3 py-2 text-sm text-white shadow hover:bg-white/10 cursor-pointer"
            >
              Manage Roles
            </button>
          </div>
          <Info
            title="Users Management"
            header={header}
            body={tableBody}
            actions={actions}
            button="↻"
            onButton={handleRefresh}
            searchConfig={{
              placeholder: "Search by username...",
              value: searchTerm,
              onChange: setSearchTerm,
            }}
            selectConfig={{
              value: roleFilter,
              onChange: (v) => setRoleFilter(v as RoleFilter),
              options: ROLES_OPTIONS,
            }}
          />
        </div>
      )}
    </div>
  );
};

export default AdminUsersPage;