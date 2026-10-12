function parseMoment(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const moment = new Date(iso).getTime();
  return Number.isNaN(moment) ? null : moment;
}

export function formatTaskMoment(iso: string | null | undefined): string | null {
  const moment = parseMoment(iso);
  return moment === null ? null : new Date(moment).toLocaleString();
}

export function formatTaskDuration(
  startIso: string | null | undefined,
  endIso: string | null | undefined
): string | null {
  const start = parseMoment(startIso);
  const end = parseMoment(endIso);
  if (start === null || end === null || end < start) return null;
  const totalSeconds = Math.round((end - start) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}
