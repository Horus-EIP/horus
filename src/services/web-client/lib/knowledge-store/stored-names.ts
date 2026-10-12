function normalizeName(name: string): string {
  return name.trim().toLowerCase();
}

export function namesAlreadyStored(names: string[], storedTitles: string[]): string[] {
  const stored = new Set(storedTitles.map(normalizeName).filter(Boolean));
  return names.filter((name) => stored.has(normalizeName(name)));
}
