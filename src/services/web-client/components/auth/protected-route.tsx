'use client';

import { ReactNode, useEffect } from 'react';
import { useAuth } from './auth-provider';
import { Spinner } from '@/components/ui/spinner';
import type { UserRole } from '@/lib/types';

interface ProtectedRouteProps {
  children: ReactNode;
  redirectTo?: string;
  allowedRoles?: UserRole[];
}

export const ProtectedRoute = ({
  children,
  redirectTo = '/auth/login',
  allowedRoles,
}: ProtectedRouteProps) => {
  const { status, user } = useAuth();

  useEffect(() => {
    if (status === 'unauthenticated') {
      window.location.replace(redirectTo);
      return;
    }

    if (
      status === 'authenticated' &&
      allowedRoles &&
      (!user || !allowedRoles.includes(user.role as UserRole))
    ) {
      window.location.href = '/dashboard';
    }
  }, [status, redirectTo, allowedRoles, user]);

  useEffect(() => {
    if (status !== 'unauthenticated') {
      return;
    }

    const redirectRestoredLoggedOutPage = (event: PageTransitionEvent) => {
      if (event.persisted) {
        window.location.replace(redirectTo);
      }
    };

    window.addEventListener('pageshow', redirectRestoredLoggedOutPage);
    return () => {
      window.removeEventListener('pageshow', redirectRestoredLoggedOutPage);
    };
  }, [status, redirectTo]);

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">
        <div className="text-center space-y-4">
          <Spinner className="text-blue-600 mx-auto" />
          <p className="text-slate-600 dark:text-slate-400">Loading...</p>
        </div>
      </div>
    );
  }

  if (
    status === 'unauthenticated' ||
    (allowedRoles &&
      (!user || !allowedRoles.includes(user.role as UserRole)))
  ) {
    return null;
  }

  return <>{children}</>;
};
