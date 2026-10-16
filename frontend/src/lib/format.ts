import i18n from "./i18n";

/** Dates are transmitted in UTC ISO 8601 and displayed in the user's locale and time zone. */
export function formatDateTime(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) return "—";
  return new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

/** File and backup sizes: binary units, locale number format. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(value);
  return `${number} ${units[unit] ?? "B"}`;
}
