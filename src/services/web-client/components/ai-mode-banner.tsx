'use client';

import { useEffect, useState } from "react";

import { systemApi, type AiMode } from "@/lib/system/api";

export const MOCK_BANNER_TEXT =
  "answers are assembled from your documents without a language model. They are simulated: use them to test Horus, not to judge its answers.";

export function AiModeBanner() {
  const [mode, setMode] = useState<AiMode | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    systemApi.getAiMode({ signal: controller.signal }).then((result) => {
      if (result.ok && result.data) setMode(result.data);
    });
    return () => controller.abort();
  }, []);

  if (mode?.mode !== "mock") return null;
  return (
    <div
      role="status"
      className="sticky top-0 z-50 border-b border-amber-500/40 bg-amber-500/15 px-4 py-2 text-center text-sm text-amber-800 dark:text-amber-200"
    >
      <strong>Mock AI mode:</strong> {MOCK_BANNER_TEXT}
    </div>
  );
}
