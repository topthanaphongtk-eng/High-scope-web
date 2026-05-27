import path from "node:path";
import { SHARE_ROOT } from "./settings";

export function fmtDt(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}  ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  for (const fmt of ["date", "datetime-seconds", "datetime"] as const) {
    const d = tryParse(s, fmt);
    if (d) return d;
  }
  return null;
}

export function parseUntil(s: string | null | undefined): Date | null {
  if (!s) return null;
  // Date-only inputs: treat as end-of-day (next-day 00:00) so a capture at
  // 14:30 on the same date passes the filter.
  const dateOnly = tryParse(s, "date");
  if (dateOnly) {
    return new Date(dateOnly.getTime() + 24 * 60 * 60 * 1000);
  }
  for (const fmt of ["datetime-seconds", "datetime"] as const) {
    const d = tryParse(s, fmt);
    if (d) return d;
  }
  return null;
}

function tryParse(
  s: string,
  fmt: "date" | "datetime" | "datetime-seconds",
): Date | null {
  const patterns: Record<typeof fmt, RegExp> = {
    "date": /^(\d{4})-(\d{2})-(\d{2})$/,
    "datetime": /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/,
    "datetime-seconds": /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/,
  };
  const m = s.match(patterns[fmt]);
  if (!m) return null;
  const [, y, mo, d, h = "0", mi = "0", se = "0"] = m;
  return new Date(
    Number(y),
    Number(mo) - 1,
    Number(d),
    Number(h),
    Number(mi),
    Number(se),
  );
}

/** Convert an absolute fused_path to a path-relative-to-share-root suitable
 * for /image?path=... — returns null if outside the share root. */
export function toImageUrl(fusedPath: string | null | undefined): string | null {
  if (!fusedPath) return null;
  try {
    const abs = path.resolve(fusedPath);
    const rel = path.relative(SHARE_ROOT, abs);
    if (rel.startsWith("..") || path.isAbsolute(rel)) return null;
    return rel.split(path.sep).join("/");
  } catch {
    return null;
  }
}

