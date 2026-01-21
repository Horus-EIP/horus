'use client';

import {
  IconDeviceDesktopAnalytics,
  IconRobot,
  IconMessages,
  IconMessageCircle,
  IconChecklist,
  IconFiles,
  IconLogout,
  IconUsersGroup
} from '@tabler/icons-react';
import { usePathname, useRouter } from 'next/navigation';
import { Center, Image, Stack, Tooltip, UnstyledButton } from '@mantine/core';
import { useAuth } from '@/components/auth/auth-provider';
import { authApi } from '@/lib/auth/api';

interface NavbarLinkProps {
  icon: typeof IconDeviceDesktopAnalytics;
  label: string;
  active?: boolean;
  onClick?: () => void;
  status?: 'active' | 'inactive';
}

function NavbarLink({ icon: Icon, label, active, onClick, status }: NavbarLinkProps) {
  const isInactive = status === 'inactive';
  return (
    <Tooltip label={label} position="right" transitionProps={{ duration: 0 }} className=''>
      <UnstyledButton
        onClick={onClick}
        className={`
          w-[30px] md:w-[50px] h-[50px] rounded-md flex items-center justify-center
          text-gray-700 dark:text-gray-200
          hover:bg-gray-100 dark:hover:bg-white/10
          data-[active]:bg-blue-50 data-[active]:text-blue-600
          dark:data-[active]:bg-blue-900/20 dark:data-[active]:text-blue-200
          ${isInactive
            ? 'opacity-40 text-gray-400 dark:text-gray-600'
            : 'cursor-pointer text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/10'
          }
        `}
        data-active={active || undefined}
      >
        <Icon size={30} stroke={1.5} cursor={isInactive ? 'not-allowed' : 'pointer'} />
      </UnstyledButton>
    </Tooltip>
  );
}

const mockdata = [
  { icon: IconDeviceDesktopAnalytics, label: 'Dashboard', status: 'active' },
  { icon: IconMessages, label: 'Chat', status: 'active' },
  { icon: IconMessageCircle, label: 'Conversations', status: 'active' },
  { icon: IconChecklist, label: 'Tasks', status: 'active' },
  { icon: IconFiles, label: 'Knowledge-Store', status: 'active' },
];

export function NavbarMinimal() {
  const pathname = usePathname();
  const router = useRouter();

  const { user } = useAuth();

  const links = mockdata.map((link) => (
    <NavbarLink
      {...link}
      key={link.label}
      active={
        (pathname === link.label.toLowerCase() || pathname?.startsWith('/' + link.label.toLowerCase())) &&
        (!pathname?.startsWith('/404') || !pathname?.startsWith('/500'))}
      onClick={() => {
        if (link.status === 'active'){
          router.push('/' + link.label.toLowerCase());
        }
      }}
      status={link.status as 'active' | 'inactive'}
    />
  ));

  return (
    <nav className="w-[60px] md:w-[80px] h-screen p-4 flex flex-col border-r border-gray-200 dark:border-white/10">
      <Center className="w-[30px] md:w-[50px]">
        <Image src="/logo.png" alt="Logo" className="w-5" />
      </Center>

      <div className="flex-1 flex flex-col justify-center">
        <Stack justify="center" gap={15}>
          {links}
        </Stack>
      </div>

      <Stack justify="center" gap={0}>
        {user?.role === 'admin' && (
          <NavbarLink
            icon={IconUsersGroup}
            label="Admin"
            active={pathname?.startsWith('/admin')}
            onClick={() => router.push('/admin/users')}
          />
        )}

        <NavbarLink
          icon={IconLogout}
          label="Logout"
          onClick={() => authApi.logout().then(() => router.push('/auth/login'))}
        />
      </Stack>
    </nav>
  );
}