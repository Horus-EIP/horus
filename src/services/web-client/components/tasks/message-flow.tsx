'use client';

import { AgentMessage, MessageType } from '@/lib/tasks/types';

const TYPE_CONFIG: Record<MessageType, { label: string; colors: string }> = {
  instruction: { label: 'Instruction', colors: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
  result:      { label: 'Result',      colors: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  question:    { label: 'Question',    colors: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  answer:      { label: 'Answer',      colors: 'bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/30' },
};

function formatTime(iso: string) {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function MessageFlow({ messages }: { messages: AgentMessage[] }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 shadow-sm backdrop-blur-sm">
      <h3 className="text-sm font-semibold text-[var(--text)] mb-3">Message Flow</h3>
      <div className="flex flex-col gap-3">
        {messages.map((msg, index) => {
          const config = TYPE_CONFIG[msg.type];
          return (
            <div key={msg.id} className="flex gap-3">
              {/* Timeline */}
              <div className="flex flex-col items-center">
                <div className="w-2 h-2 rounded-full bg-white/20 mt-1.5 flex-shrink-0" />
                {index < messages.length - 1 && (
                  <div className="w-px flex-1 bg-white/10 mt-1" />
                )}
              </div>
              {/* Content */}
              <div className="flex flex-col gap-1 pb-2 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-[var(--text)]">{msg.fromAgent}</span>
                  <span className="text-[10px] text-[var(--textSoft)]">→</span>
                  <span className="text-xs font-medium text-[var(--text)]">{msg.toAgent}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${config.colors}`}>
                    {config.label}
                  </span>
                  <span className="text-[10px] text-[var(--textSoft)] ml-auto">{formatTime(msg.timestamp)}</span>
                </div>
                <p className="text-xs text-[var(--textSoft)]">{msg.content}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}