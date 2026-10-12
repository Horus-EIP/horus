'use client';

import {
  IconDeviceDesktopAnalytics,
  IconMessages,
  IconChecklist,
  IconFiles,
  IconLogout,
  IconLogs,
  IconChartArea,
  IconBinaryTree2,
  IconUsersGroup
} from '@tabler/icons-react';
import { usePathname, useRouter } from 'next/navigation';
import { Center, Image, Stack, Tooltip, UnstyledButton } from '@mantine/core';
import { useAuth } from '@/components/auth/auth-provider';

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
        aria-label={label}
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
  { icon: IconChecklist, label: 'Tasks', status: 'active' },
  { icon: IconFiles, label: 'Knowledge-Store', status: 'active' },
];

export function NavbarMinimal() {
  const pathname = usePathname();
  const router = useRouter();

  const { user, logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    router.replace('/auth/login');
  };

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
          <>
            <NavbarLink
              icon={IconUsersGroup}
              label="Admin"
              active={
                pathname?.startsWith('/admin') &&
                !pathname?.startsWith('/admin/logs') &&
                !pathname?.startsWith('/admin/metrics') &&
                !pathname?.startsWith('/admin/traces')
              }
              onClick={() => router.push('/admin/users')}
            />
            <NavbarLink
              icon={IconLogs}
              label="Logs"
              active={pathname?.startsWith('/admin/logs')}
              onClick={() => router.push('/admin/logs')}
            />
            <NavbarLink
              icon={IconChartArea}
              label="Metrics"
              active={pathname?.startsWith('/admin/metrics')}
              onClick={() => router.push('/admin/metrics')}
            />
            <NavbarLink
              icon={IconBinaryTree2}
              label="Traces"
              active={pathname?.startsWith('/admin/traces')}
              onClick={() => router.push('/admin/traces')}
            />
          </>
        )}

        <NavbarLink
          icon={IconLogout}
          label="Logout"
          onClick={() => void handleLogout()}
        />
      </Stack>
    </nav>
  );
}