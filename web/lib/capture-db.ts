import { DatabaseSync } from "node:sqlite";
import { DB_PATH } from "./settings";
import { toIsoLocal } from "./format";
import type {
  BucketCounts,
  Capture,
  CaptureFile,
  CaptureFilter,
  LotSummary,
} from "./types";

interface JoinedRow {
  capture_id: string;
  confirmed_at: string;
  lot_id: string;
  bonding_number: string | null;
  lot_location: string | null;
  mpc: string | null;
  package: string | null;
  qs: string | null;
  operator_badge: string;
  hostname: string | null;
  app_version: string | null;
  mode: string;
  raw_lot_info: string | null;
  slot: string | null;
  fused_path: string | null;
  fused_name: string | null;
  file_size_bytes: number | null;
  file_sha256: string | null;
}

function open(): DatabaseSync {
  return new DatabaseSync(DB_PATH, { readOnly: true });
}

/** Build WHERE clauses + params from a filter, sharing the construction
 * between `recentCaptures`, `countCaptures`, and any future readers. */
function buildWhere(filter: CaptureFilter): {
  where: string;
  params: (string | number)[];
} {
  const clauses: string[] = [];
  const params: (string | number)[] = [];
  if (filter.since) {
    clauses.push("c.confirmed_at >= ?");
    params.push(toIsoLocal(filter.since));
  }
  if (filter.until) {
    clauses.push("c.confirmed_at <= ?");
    params.push(toIsoLocal(filter.until));
  }
  if (filter.bonding_number != null) {
    clauses.push("c.bonding_number = ?");
    params.push(filter.bonding_number);
  }
  if (filter.lot_location != null) {
    clauses.push("COALESCE(c.lot_location, '') = ?");
    params.push(filter.lot_location);
  }
  if (filter.lot_id != null) {
    clauses.push("c.lot_id = ?");
    params.push(filter.lot_id);
  }
  if (filter.mode != null) {
    clauses.push("c.mode = ?");
    params.push(filter.mode);
  }
  return {
    where: clauses.length ? `WHERE ${clauses.join(" AND ")}` : "",
    params,
  };
}

export function recentCaptures(filter: CaptureFilter = {}): Capture[] {
  const limit = filter.limit ?? 50;
  const offset = filter.offset ?? 0;
  const { where, params } = buildWhere(filter);

  // CTE picks the page of capture_ids first, then we JOIN in files for just
  // those rows. Avoids the old "LIMIT * 4" trick and supports OFFSET cleanly.
  const sql = `
    WITH paged AS (
      SELECT capture_id
      FROM captures c
      ${where}
      ORDER BY c.confirmed_at DESC, c.capture_id
      LIMIT ? OFFSET ?
    )
    SELECT c.*, f.slot, f.fused_path, f.fused_name,
           f.size_bytes AS file_size_bytes, f.sha256 AS file_sha256
    FROM captures c
    INNER JOIN paged p ON p.capture_id = c.capture_id
    LEFT JOIN capture_files f ON f.capture_id = c.capture_id
    ORDER BY c.confirmed_at DESC, c.capture_id, f.id
  `;

  const db = open();
  let rows: JoinedRow[];
  try {
    rows = db.prepare(sql).all(...params, limit, offset) as JoinedRow[];
  } finally {
    db.close();
  }

  const grouped = new Map<string, Capture>();
  const order: string[] = [];

  for (const r of rows) {
    let cap = grouped.get(r.capture_id);
    if (!cap) {
      cap = {
        capture_id: r.capture_id,
        confirmed_at: r.confirmed_at,
        lot_id: r.lot_id,
        bonding_number: r.bonding_number,
        lot_location: r.lot_location,
        mpc: r.mpc,
        package: r.package,
        qs: r.qs,
        operator_badge: r.operator_badge,
        hostname: r.hostname,
        app_version: r.app_version,
        mode: r.mode,
        raw_lot_info: r.raw_lot_info,
        files: [],
      };
      grouped.set(r.capture_id, cap);
      order.push(r.capture_id);
    }
    if (r.slot != null && r.fused_path != null && r.fused_name != null) {
      const file: CaptureFile = {
        slot: r.slot,
        fused_path: r.fused_path,
        fused_name: r.fused_name,
        size_bytes: r.file_size_bytes,
        sha256: r.file_sha256,
      };
      cap.files.push(file);
    }
  }

  const out = order.map((id) => grouped.get(id)!);
  for (const c of out) {
    if (typeof c.raw_lot_info === "string") {
      try {
        c.raw_lot_info = JSON.parse(c.raw_lot_info);
      } catch {
        // leave as string if not valid JSON
      }
    }
  }
  return out;
}

export function countCaptures(filter: CaptureFilter = {}): number {
  const { where, params } = buildWhere(filter);
  const db = open();
  try {
    const row = db
      .prepare(`SELECT COUNT(*) AS n FROM captures c ${where}`)
      .get(...params) as { n: number } | undefined;
    return row?.n ?? 0;
  } finally {
    db.close();
  }
}

/** Compute today/week/month/total counts in a single trip via SQL — much
 * cheaper than reading thousands of rows into memory just to count. */
export function bucketCounts(now: Date = new Date()): BucketCounts {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  const weekEnd = new Date(weekStart);
  weekEnd.setDate(weekStart.getDate() + 7);
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);

  const todayS = toIsoLocal(today);
  const tomorrowS = toIsoLocal(tomorrow);
  const weekStartS = toIsoLocal(weekStart);
  const weekEndS = toIsoLocal(weekEnd);
  const monthStartS = toIsoLocal(monthStart);

  const db = open();
  try {
    const row = db
      .prepare(
        `SELECT
           SUM(CASE WHEN confirmed_at >= ? AND confirmed_at < ? THEN 1 ELSE 0 END) AS today,
           SUM(CASE WHEN confirmed_at >= ? AND confirmed_at < ? THEN 1 ELSE 0 END) AS week,
           SUM(CASE WHEN confirmed_at >= ? AND confirmed_at < ? THEN 1 ELSE 0 END) AS month,
           COUNT(*) AS total
         FROM captures`,
      )
      .get(
        todayS,
        tomorrowS,
        weekStartS,
        weekEndS,
        monthStartS,
        tomorrowS,
      ) as
      | { today: number | null; week: number | null; month: number | null; total: number }
      | undefined;
    return {
      today: row?.today ?? 0,
      week: row?.week ?? 0,
      month: row?.month ?? 0,
      total: row?.total ?? 0,
    };
  } finally {
    db.close();
  }
}

export function lotCaptures(lotId: string): Capture[] {
  return recentCaptures({ lot_id: lotId, limit: 500 });
}

export function allLots(limit = 200): LotSummary[] {
  const db = open();
  try {
    return db
      .prepare(
        `SELECT lot_id,
                MAX(confirmed_at) AS last_confirmed_at,
                COUNT(*) AS capture_count
         FROM captures
         GROUP BY lot_id
         ORDER BY last_confirmed_at DESC
         LIMIT ?`,
      )
      .all(limit) as LotSummary[];
  } finally {
    db.close();
  }
}
