import {
  Box,
  Card,
  Heading,
  Text,
  Badge,
  Button,
  SimpleGrid,
  HStack,
  Separator
} from '@chakra-ui/react'

import React from 'react';

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
]

export default function RoleCards() {
  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-2 md:p-4 shadow-xl backdrop-blur-xl">
        <h2 className="text-lg font-semibold text-[var(--text)] mb-3">Roles Management</h2>
        <SimpleGrid gap={4} templateColumns='repeat(auto-fit, minmax(300px, 1fr))'>

          {roles.map((role) => (
            <Card.Root key={role.id} borderTopWidth="4px" borderColor="whiteAlpha.400" overflow="hidden" bg={'var(--bgSoft)'}>

              <Card.Header pb={0}>
                <HStack justify="space-between" align="start">
                  <Box>
                    <Heading size='md'>{role.title}</Heading>
                    <Text color='gray.500' fontSize='sm' mt={1}>
                      {role.description}
                    </Text>
                  </Box>
                  <Badge colorPalette='var(--bgSoft)' borderRadius='full' px={2}>
                    {role.perms.length} perms
                  </Badge>
                </HStack>
              </Card.Header>

              <Card.Body>
                <Text fontSize='xs' fontWeight='bold' color='gray.400' mb={3} textTransform="uppercase">
                  Access Scope
                </Text>
                <HStack gap={2} wrap="wrap">
                  {role.perms.map((perm, index) => (
                    <Badge key={index} variant='outline' px={2} py={1} borderRadius="md" fontWeight="normal">
                      {perm}
                    </Badge>
                  ))}
                </HStack>
              </Card.Body>

              <Separator borderColor={'whiteAlpha.200'} />

              <Card.Footer justifyContent='flex-end' display='flex'>
                <HStack gap={4} pt={2}>
                  <Button variant='ghost' colorPalette='blue' size='sm' cursor={'not-allowed'}>
                    Edit
                  </Button>
                  <Button variant='ghost' colorPalette='red' size='sm' cursor={'not-allowed'}>
                    Delete
                  </Button>
                </HStack>
              </Card.Footer>
            </Card.Root>
          ))}
        </SimpleGrid>
      </div>
    </div>
  )
}