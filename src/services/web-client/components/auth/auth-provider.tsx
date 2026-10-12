'use client';

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { authApi } from '@/lib/auth/api';
import { userApi } from '@/lib/users/api';
import type { User } from '@/lib/types';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextType {
  user: User | null;
  status: AuthStatus;
  login: (
    username: string,
    password: string
  ) => Promise<{ ok: boolean; error?: string }>;
  register: (
    username: string,
    password: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  const refresh = async () => {
    setStatus('loading');

    const currentUser = await userApi.getCurrentUser();

    if (currentUser) {
      setUser(currentUser);
      setStatus('authenticated');
    } else {
      setUser(null);
      setStatus('unauthenticated');
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const recheckSessionOnBackForwardRestore = (event: PageTransitionEvent) => {
      if (event.persisted) {
        void refresh();
      }
    };

    window.addEventListener('pageshow', recheckSessionOnBackForwardRestore);
    return () => {
      window.removeEventListener('pageshow', recheckSessionOnBackForwardRestore);
    };
  }, []);

  const login = async (username: string, password: string) => {
    const result = await authApi.login({ username, password });

    if (result.ok && result.user) {
      setUser(result.user);
      setStatus('authenticated');
    } else if (!result.ok) {
      setUser(null);
      setStatus('unauthenticated');
    }

    return { ok: result.ok, error: result.error };
  };

  const register = async (
    username: string,
    password: string
  ) => {
    const result = await authApi.register({
      username,
      password,
      confirmPassword: password,
    });

    if (result.ok && result.user) {
      setUser(result.user);
      setStatus('authenticated');
    } else if (!result.ok) {
      setUser(null);
      setStatus('unauthenticated');
    }

    return { ok: result.ok, error: result.error };
  };

  const logout = async () => {
    await authApi.logout();
    setUser(null);
    setStatus('unauthenticated');
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        status,
        login,
        register,
        logout,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
