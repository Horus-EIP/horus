'use client';

export default function Card({ title, number }: { title: string; number: number }) {
  return (
    <div className="group relative w-full transition-transform duration-200 hover:-translate-y-0.5">
      <div className="absolute inset-px rounded-2xl bg-gradient-to-br from-cyan-400/25 via-fuchsia-400/15 to-indigo-400/25 blur-sm opacity-60 group-hover:opacity-90 transition-opacity"></div>

      <div className="relative rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 md:p-5 shadow-sm backdrop-blur-sm">
        <div className="flex items-start md:items-baseline justify-between gap-1">
          <span className="text-[var(--textSoft)] text-xs md:text-sm font-medium">
            {title}
          </span>
        </div>

        <div className="mt-1 md:mt-2 text-2xl md:text-4xl font-semibold text-[var(--text)] tabular-nums">
          {number}
        </div>
      </div>
    </div>
  );
}
