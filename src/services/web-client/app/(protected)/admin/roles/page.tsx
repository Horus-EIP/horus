'use client';

import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';

const roles = [
  {
    id: 1,
    title: 'Admin',
    description: 'Full system access',
    perms: ['Export Data', 'System Config', 'Create Users', 'Read Users', 'Edit Users', 'Delete Users', 'Create Tasks', 'Read Tasks', 'Edit Tasks', 'Delete Tasks', 'Approve Tasks', 'Create Agents', 'Read Agents', 'Edit Agents', 'Delete Agents', 'Execute Agents', 'View Analytics']
  },
  {
    id: 2,
    title: 'Manager',
    description: 'Can manage content and users',
    perms: ['Export Data', 'System Config', 'Create Tasks', 'Read Tasks', 'Edit Tasks', 'Delete Tasks', 'Approve Tasks', 'Read Users', 'View Analytics', 'Read Agents', 'Execute Agents']
  },
  {
    id: 3,
    title: 'User',
    description: 'Basic access to own data',
    perms: ['Create Tasks', 'Read Tasks', 'Read Agents', 'Execute Agents']
  }
];

export default function RoleCards() {
  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-2 md:p-4 shadow-xl backdrop-blur-xl">
        <h2 className="text-lg font-semibold text-[var(--text)] mb-3">Roles Management</h2>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {roles.map((role) => (
            <Card
              key={role.id}
              padding="lg"
              radius="md"
              withBorder
              style={{
                background: 'var(--bgSoft)',
                borderTopWidth: 4,
                borderTopColor: 'rgba(255,255,255,0.35)',
              }}
            >
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <div>
                    <Title order={4}>{role.title}</Title>
                    <Text size="sm" c="dimmed" mt={4}>
                      {role.description}
                    </Text>
                  </div>
                  <Badge variant="light" radius="xl">
                    {role.perms.length} perms
                  </Badge>
                </Group>

                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Access Scope
                </Text>
                <Group gap={6} wrap="wrap">
                  {role.perms.map((perm, index) => (
                    <Badge key={index} variant="outline" radius="md" fw={400}>
                      {perm}
                    </Badge>
                  ))}
                </Group>

                <Divider color="dark.4" />

                <Group justify="flex-end" gap="md" pt="xs">
                  <Button variant="subtle" size="xs" disabled>
                    Edit
                  </Button>
                  <Button variant="subtle" color="red" size="xs" disabled>
                    Delete
                  </Button>
                </Group>
              </Stack>
            </Card>
          ))}
        </SimpleGrid>
      </div>
    </div>
  );
}
