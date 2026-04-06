'use client';

import type { ReactNode } from "react";
import { useRef, useState } from "react";

import { ProtectedRoute } from "@/components/auth/protected-route";
import { NavbarMinimal } from "@/components/ui/mantine/navbar/navbar-minimal";
import { MantineProvider } from "@mantine/core";
import { ModalsProvider } from '@mantine/modals';
import Navbar from "@/components/ui/navbar";

import {
  ChakraProvider,
  createSystem,
  defaultConfig,
  defineConfig
} from "@chakra-ui/react";

const customConfig = defineConfig({
  preflight: false,
})

const system = createSystem(defaultConfig, customConfig)

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const toggleSidebar = () => setSidebarOpen((s) => !s);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  return (
    <ProtectedRoute>
      <div className="min-h-screen w-full text-[var(--text)] text-[clamp(13px,1.1vw,16px)] bg-[var(--bg)]">
        <div className="mx-auto flex max-h-screen max-w-[1600px] gap-3 sm:gap-4 lg:gap-6">
          <MantineProvider>
            <NavbarMinimal />
            <main className="flex-1 flex flex-col min-h-0 p-2 sm:p-3 lg:pt-4 lg:pr-4 lg:pb-4 lg:pl-0 mb-0">
              <div className="z-30 shrink-0">
                <Navbar onToggleSidebar={toggleSidebar} sidebarOpen={sidebarOpen} />
              </div>
              <div
                ref={scrollContainerRef}
                className="sm:mt-4 overflow-y-auto main-scroll w-full scroll-smooth overflow-x-hidden chat-scroll"
              >
                <ChakraProvider value={system}>
                  <ModalsProvider>
                    {children}
                  </ModalsProvider>
                </ChakraProvider>
              </div>
            </main>
          </MantineProvider>
        </div>
      </div>
    </ProtectedRoute>
  );
}