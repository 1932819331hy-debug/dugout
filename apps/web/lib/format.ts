// Formatting shared by server and client components.
const SOURCE_NAMES: Record<string, string> = {
  fpl: "Fantasy Premier League",
  football_data_org: "football-data.org",
  transfermarkt: "Transfermarkt",
  wikidata: "Wikidata",
  api_football: "API-Football",
};

export function sourceName(source: string): string {
  if (source.startsWith("dugout_model:")) return `dugout ${source.split(":")[1]} model`;
  return SOURCE_NAMES[source] ?? source;
}

export function when(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    }) + " UTC"
  );
}

export function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${s}`;
}
