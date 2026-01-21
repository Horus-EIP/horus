export const formatTimestamp = (date: Date) => {
  const d = new Date(date);
  const now = new Date();

  const isToday =
    d.getDate() === now.getDate() &&
    d.getMonth() === now.getMonth() &&
    d.getFullYear() === now.getFullYear();

  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  if (isToday) return time;

  const dayMonth = d.toLocaleDateString([], {
    day: "2-digit",
    month: "2-digit",
  });
  return `${dayMonth} ${time}`;
};
