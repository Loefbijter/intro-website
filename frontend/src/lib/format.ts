export function formatDutchDate(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`);
  const formatted = new Intl.DateTimeFormat("nl-NL", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(date);
  return formatted;
}
