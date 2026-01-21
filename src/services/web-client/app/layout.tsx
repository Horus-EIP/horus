'use client';

import type { ReactNode } from "react";
import { Toaster } from "react-hot-toast";

import { AuthProvider } from "@/components/auth/auth-provider";
import { NotificationProvider } from "@/contexts/notification-context";

import "@/styles/globals.css";
import "@mantine/core/styles.css";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-[var(--bg)]">
        <NotificationProvider>
          <AuthProvider>
            { children }
          </AuthProvider>
        </NotificationProvider>
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
