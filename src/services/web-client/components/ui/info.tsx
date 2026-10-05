'use client';

import type { ReactNode } from 'react';

interface SearchConfig {
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
}

interface SelectOption {
  value: string;
  label: string;
}

interface SelectConfig {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
}

interface RowAction {
  icon: ReactNode;
  ariaLabel?: string;
  onClick: (rowIndex: number) => void;
}

interface Props {
  title?: string;
  header: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any[][];
  actions?: RowAction[];
  button?: string;
  onButton?: () => void;
  link?: string;
  indexLink?: number;
  searchConfig?: SearchConfig;
  selectConfig?: SelectConfig;
}

const statusClass = (val: string) => {
  const v = (val || '').toLowerCase();
  if (['online', 'completed'].includes(v)) {
    return 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30';
  }
  if (['idle', 'running'].includes(v)) {
    return 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30';
  }
  if (['busy', 'processing'].includes(v)) {
    return 'bg-rose-500/20 text-rose-300 ring-1 ring-rose-500/30';
  }
  if (v === 'pending' || v === 'queued') {
    return 'bg-gray-500/20 text-gray-300 ring-1 ring-gray-500/30';
  }
  if (v === 'offline'){
    return 'bg-red-500/20 text-red-400 ring-1 ring-red-500/30';
  }
  return '';
};

const LONG_TEXT_MIN_LENGTH = 40;

const textCellClass = (text: string) =>
  text.length >= LONG_TEXT_MIN_LENGTH
    ? 'min-w-48 max-w-xs line-clamp-3 wrap-anywhere'
    : 'block max-w-xs wrap-break-word';

export default function Info({
  title,
  header,
  body,
  actions,
  button,
  onButton,
  link,
  indexLink,
  searchConfig,
  selectConfig,
}: Props) {
  const hasHeaderControls =
    Boolean(searchConfig) || Boolean(selectConfig) || Boolean(button);

  const hasRowActions = Array.isArray(actions) && actions.length > 0;

  return (
    <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-2 md:p-4 shadow-xl backdrop-blur-xl">
      <div className="mb-3 flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:justify-between">
        <h2 className="text-lg font-semibold text-[var(--text)]">{title}</h2>

        {hasHeaderControls && (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            {searchConfig && (
              <input
                type="text"
                placeholder={searchConfig.placeholder ?? 'Search...'}
                className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--textSoft)] sm:w-56"
                value={searchConfig.value}
                onChange={(e) => searchConfig.onChange(e.target.value)}
              />
            )}

            {selectConfig && (
              <select
                className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-[var(--text)] outline-none sm:w-40"
                value={selectConfig.value}
                onChange={(e) => selectConfig.onChange(e.target.value)}
              >
                {selectConfig.options.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            )}

            {button && (
              <button
                className="rounded-xl bg-white/5 px-3 py-2 text-sm text-white shadow hover:bg-white/10 cursor-pointer"
                onClick={onButton}
              >
                {button}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full text-sm">
          <thead className="bg-white/5">
            <tr>
              {header?.map((item, index) => (
                <th
                  key={index}
                  className="whitespace-nowrap px-3 py-2 text-left font-semibold text-[var(--textSoft)]"
                >
                  {item}
                </th>
              ))}
              {hasRowActions && (
                <th className="w-20 px-3 py-2 text-right font-semibold text-[var(--textSoft)]">
                  {/* Actions */}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {body?.map((row, rIndex) => (
              <tr
                key={rIndex}
                className="odd:bg-white/0 even:bg-white/[0.03]"
              >
                {row.map((data, cIndex) => (
                  <td
                    key={cIndex}
                    className="px-3 py-2 align-middle text-[var(--text)]"
                  >
                    {typeof data === 'string' && statusClass(data) ? (
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(
                          data,
                        )}`}
                      >
                        {data}
                      </span>
                    ) : link && cIndex === indexLink ? (
                      <a
                        className="text-sky-300 underline-offset-2 hover:underline"
                        href={link.concat(String(row[5] ?? ''))}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {String(data)}
                      </a>
                    ) : (
                      typeof data === 'object' && data !== null && !Array.isArray(data) ? (
                      <span>{data as ReactNode}</span>
                    ) : (
                      <span title={String(data)} className={textCellClass(String(data))}>{String(data)}</span>
                    )
                    )}
                  </td>
                ))}

                {hasRowActions && (
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {actions!.map((action, actionIndex) => (
                        <button
                          key={actionIndex}
                          type="button"
                          aria-label={action.ariaLabel ?? 'Row action'}
                          onClick={() => action.onClick(rIndex)}
                          className="rounded-lg p-2 text-[var(--textSoft)] hover:bg-white/10"
                        >
                          {action.icon}
                        </button>
                      ))}
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
