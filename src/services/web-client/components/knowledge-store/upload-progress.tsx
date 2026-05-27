'use client';

import { Progress, Text } from '@mantine/core';
import { IconCheck, IconAlertTriangle, IconLoader2 } from '@tabler/icons-react';
import {
  formatBytes,
  formatEta,
  type UploadProgress as UploadProgressData,
} from '@/lib/knowledge-store/api';

interface UploadProgressProps {
  progress: UploadProgressData;
  /** Optional detail string from the API response — surfaced verbatim in the
   * error state so the user (and the developer reading bug reports) can see
   * the real cause, not just a generic line. */
  errorDetail?: string | null;
}

/** Single panel that morphs through the upload → processing → done phases.
 *
 * - `uploading`: real progress bar + bytes sent / total + ETA.
 * - `processing`: indeterminate bar + "indexing in the knowledge store" hint.
 *   The KS extracts text and runs analysis on the server, so we can't compute
 *   a true ETA here — be honest about that instead of faking one.
 * - `done`: green check + size summary.
 * - `error`: red triangle + message.
 */
export function UploadProgress({ progress, errorDetail }: UploadProgressProps) {
  const { phase, loadedBytes, totalBytes, etaSeconds, bytesPerSecond } =
    progress;
  const pct =
    totalBytes > 0 ? Math.min(100, (loadedBytes / totalBytes) * 100) : 0;

  if (phase === 'error') {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
        <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p>Upload failed.</p>
          {errorDetail && (
            <p className="text-xs text-red-300/80 break-words">{errorDetail}</p>
          )}
          <p className="text-xs text-red-300/60">
            Open DevTools → Network for the full request detail.
          </p>
        </div>
      </div>
    );
  }

  if (phase === 'done') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
        <IconCheck size={16} />
        <span>
          Uploaded and indexed ({formatBytes(totalBytes)}).
        </span>
      </div>
    );
  }

  if (phase === 'processing') {
    return (
      <div className="space-y-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
        <div className="flex items-center justify-between gap-2 text-sm">
          <div className="flex items-center gap-2 text-[var(--text)]">
            <IconLoader2 size={16} className="animate-spin text-sky-300" />
            <span>Indexing in the knowledge store…</span>
          </div>
          <Text size="xs" c="dimmed">
            {formatBytes(totalBytes)} uploaded
          </Text>
        </div>
        <Progress value={100} animated striped size="sm" color="cyan" />
        <Text size="xs" c="dimmed">
          The store is extracting text and running analysis. Large PDFs can
          take a moment.
        </Text>
      </div>
    );
  }

  // phase === 'uploading'
  return (
    <div className="space-y-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-sm">
        <div className="flex items-center gap-2 text-[var(--text)]">
          <IconLoader2 size={16} className="animate-spin text-sky-300" />
          <span>Uploading…</span>
        </div>
        <Text size="xs" c="dimmed">
          {formatBytes(loadedBytes)} / {formatBytes(totalBytes)}
        </Text>
      </div>
      <Progress value={pct} size="sm" color="blue" />
      <div className="flex justify-between text-xs text-[var(--textSoft)]">
        <span>{formatEta(etaSeconds)}</span>
        {bytesPerSecond > 0 && (
          <span>{formatBytes(bytesPerSecond)}/s</span>
        )}
      </div>
    </div>
  );
}
