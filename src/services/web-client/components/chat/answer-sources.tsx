'use client';

import React from "react";
import { IconExternalLink, IconFileText } from "@tabler/icons-react";
import type { AnswerSource } from "@/lib/types";
import {
  distinctSources,
  knowledgeStoreDocumentHref,
  sourceLabel,
} from "@/lib/chat/answer-sources";

const SOURCE_CHIP =
  "inline-flex max-w-full items-center gap-1 rounded-full border border-gray-300 bg-[var(--bg)] px-2 py-0.5 text-[11px] text-[var(--text)] dark:border-gray-700";

export function AnswerSources({ sources }: { sources?: AnswerSource[] }) {
  const shown = distinctSources(sources ?? []);
  if (shown.length === 0) return null;

  return (
    <div className="mt-2 border-t border-gray-200 pt-2 dark:border-gray-700">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--textSoft)]">
        Sources
      </p>
      <ul aria-label="Sources" className="flex flex-wrap gap-1">
        {shown.map((source) => {
          const label = sourceLabel(source);
          const href = knowledgeStoreDocumentHref(source);
          const key = `${source.doc_id ?? ""}|${label}`;
          return (
            <li key={key} className="min-w-0 max-w-full">
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`Open ${label} in the knowledge store`}
                  className={`${SOURCE_CHIP} hover:border-blue-500/50 hover:text-blue-600 dark:hover:text-blue-300`}
                >
                  <IconFileText className="h-3 w-3 flex-none" stroke={1.5} aria-hidden />
                  <span className="truncate">{label}</span>
                  <IconExternalLink className="h-3 w-3 flex-none opacity-60" stroke={1.5} aria-hidden />
                </a>
              ) : (
                <span className={SOURCE_CHIP}>
                  <IconFileText className="h-3 w-3 flex-none" stroke={1.5} aria-hidden />
                  <span className="truncate">{label}</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
