const nf = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return nf.format(n);
}

export function formatCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Math.abs(n) < 10000 ? nf.format(n) : compact.format(n);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 45) return "just now";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return new Date(iso).toLocaleDateString();
}

export function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 1e6) / 1e6);
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Classify a DuckDB type name for alignment, icons and chart field validation. */
export type TypeKind = "number" | "text" | "temporal" | "boolean" | "other";

export function typeKind(t: string): TypeKind {
  const u = t.toUpperCase();
  if (/^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|UHUGEINT|FLOAT|DOUBLE|REAL|DECIMAL)/.test(u))
    return "number";
  if (/^(DATE|TIMESTAMP|TIME)/.test(u)) return "temporal";
  if (u === "BOOLEAN") return "boolean";
  if (u.startsWith("VARCHAR") || u === "UUID" || u.startsWith("ENUM")) return "text";
  return "other";
}
