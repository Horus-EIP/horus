'use client';

import type { ReactNode } from "react";
import { MantineProvider } from "@mantine/core";
import { Toaster } from "react-hot-toast";

import { AuthProvider } from "@/components/auth/auth-provider";
import { NotificationProvider } from "@/contexts/notification-context";

import "@/styles/globals.css";
import "@mantine/core/styles.css";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-[var(--bg)]">
        <MantineProvider defaultColorScheme="dark">
          <NotificationProvider>
            <AuthProvider>
              {children}
            </AuthProvider>
          </NotificationProvider>
        </MantineProvider>
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
