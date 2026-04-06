'use client';

import { DelegationStep } from '@/lib/tasks/types';

function formatTime(iso: string) {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function DelegationChain({ steps }: { steps: DelegationStep[] }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 shadow-sm backdrop-blur-sm">
      <h3 className="text-sm font-semibold text-[var(--text)] mb-3">Delegation Chain</h3>
      <div className="flex items-start gap-0 overflow-x-auto pb-2">
        {steps.map((step, index) => (
          <div key={index} className="flex items-center flex-shrink-0">
            {/* Node */}
            <div className="flex flex-col items-center gap-1 px-2">
              <div className={`w-8 h-8 rounded-full border flex items-center justify-center text-[10px] font-bold
                ${index === steps.length - 1
                  ? 'border-amber-500/50 bg-amber-500/10 text-amber-400'
                  : 'border-white/20 bg-white/5 text-[var(--textSoft)]'
                }`}>
                {step.agentName.slice(0, 2).toUpperCase()}
              </div>
              <span className="text-[10px] font-medium text-[var(--text)] text-center max-w-16 truncate">
                {step.agentName}
              </span>
              <span className="text-[10px] text-[var(--textSoft)] text-center max-w-20 leading-tight">
                {step.action}
              </span>
              <span className="text-[10px] text-[var(--textSoft)]">{formatTime(step.timestamp)}</span>
            </div>
            {/* Arrow */}
            {index < steps.length - 1 && (
              <span className="text-white/20 text-sm flex-shrink-0 -mt-8">→</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}