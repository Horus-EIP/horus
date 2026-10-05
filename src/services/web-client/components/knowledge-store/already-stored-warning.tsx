import type { ReactNode } from 'react';
import { IconAlertTriangle } from '@tabler/icons-react';

interface AlreadyStoredWarningProps {
  names: string[];
  children: ReactNode;
  className?: string;
}

export function AlreadyStoredWarning({ names, children, className = '' }: AlreadyStoredWarningProps) {
  if (!names.length) return null;
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200 ${className}`}
    >
      <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
      <p>
        Already in the knowledge store: <strong>{names.join(', ')}</strong>. {children}
      </p>
    </div>
  );
}
