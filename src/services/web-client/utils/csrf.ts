export const getCsrfToken = (): string | null => {
  if (typeof document === "undefined") return null;

  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta?.getAttribute("content") || null;
};

export const getCsrfHeaders = (): Record<string, string> => {
  const token = getCsrfToken();
  return token ? { "X-CSRF-Token": token } : {};
};
