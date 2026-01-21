'use client';

import { ReactNode } from 'react';
import { motion } from 'framer-motion';
import Image from 'next/image';

interface AuthLayoutProps {
  children: ReactNode;
  title: string;
  subtitle?: string;
}

export const AuthLayout = ({ children, title, subtitle }: AuthLayoutProps) => {
  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-blue-600 via-blue-700 to-slate-800">
        <div className="absolute inset-0 bg-grid-white/[0.05] bg-[size:20px_20px]" />

        <div className="relative z-10 flex flex-col items-start justify-center px-16 py-12 text-white">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="space-y-6"
          >
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 bg-white/10 backdrop-blur-sm rounded-xl flex items-center justify-center">
                <Image className="w-10 h-10" src='/logo.png' alt='' width={500} height={500} />
              </div>
              <h1 className="text-3xl font-bold">Horus Project</h1>
            </div>

            <div className="space-y-4 max-w-md">
              <h2 className="text-4xl font-bold leading-tight">
                The AI Infrastructure for Multi-Agent Collaboration
              </h2>
              <p className="text-lg text-blue-100">
                A system where AI isn&apos;t just automation, but a network of intelligent agent the learn, collaborate, and evolve.
              </p>
            </div>

            <div className="mt-12 space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-blue-300 mt-2" />
                <div>
                  <h3 className="font-semibold">AI Multi-Agent</h3>
                  <p className="text-blue-100 text-sm">Multiple AI agents collaborate, each with a specific role, just like a well-structured company</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-blue-300 mt-2" />
                <div>
                  <h3 className="font-semibold">Real Time Decisions</h3>
                  <p className="text-blue-100 text-sm">Uses RAG to gather data and an agentic AI approach to apply intelligent decisions instantly</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-blue-300 mt-2" />
                <div>
                  <h3 className="font-semibold">Machine Learning</h3>
                  <p className="text-blue-100 text-sm">Self-improving AI through ongoing Machine Learning pipelines</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-blue-300 mt-2" />
                <div>
                  <h3 className="font-semibold">Safety & Flexibility</h3>
                  <p className="text-blue-100 text-sm">Fully self-hosted by default, ensuring complete data protection and privacy</p>
                </div>
              </div>
            </div>
          </motion.div>
        </div>

        <div className="absolute bottom-0 right-0 w-96 h-96 bg-blue-500/30 rounded-full blur-3xl" />
        <div className="absolute top-0 left-0 w-96 h-96 bg-slate-500/20 rounded-full blur-3xl" />
      </div>

      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-slate-50 dark:bg-slate-900 bg-[var(--bg)]">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="w-full max-w-md"
        >
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl p-8 space-y-6">
            <div className="space-y-2">
              <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
                {title}
              </h2>
              {subtitle && (
                <p className="text-slate-600 dark:text-slate-400">
                  {subtitle}
                </p>
              )}
            </div>

            {children}
          </div>

          <p className="mt-6 text-center text-sm text-slate-600 dark:text-slate-400">
            By continuing, you agree to our Terms of Service and Privacy Policy
          </p>
        </motion.div>
      </div>
    </div>
  );
};
