import { Pool, types } from "pg";
import { getPgConfig } from "./settings";
import type {
  BucketCounts,
  Capture,
  CaptureFile,
  CaptureFilter,
  LotSummary,
} from "./types";

// node-postgres returns BIGINT (OID 20) as a string to avoid precision loss.
// Our only bigints are size_bytes and ids, all well under 2^53 — parse to
// number so the API shape matches what the UI expects.
types.setTypeParser(20, (val) => (val === null ? null : Number(val)));

interface JoinedRow {
  capture_id: string;
  confirmed_at: Date;
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
  raw_lot_info: Record<string, unknown> | string | null;
  slot: string | null;
  fused_path: string | null;
  fused_name: string | null;
  file_size_bytes: number | null;
  file_sha256: string | null;
}

let pool: Pool | null = null;

/** Lazy, shared connection pool. pg's Pool manages many connections
 * internally — opening one per request is the wrong shape here. getPgConfig()
 * is called here (not at import) so DB config is only required at query time. */
function getPool(): Pool {
  if (!pool) pool = new Pool(getPgConfig());
  return pool;
}

/** Append filter clauses to `params` (mutated) and return the WHERE fragment
 * with $N placeholders. Shared by recentCaptures and countCaptures so the
 * WHERE shape stays in sync. */
function applyFilter(filter: CaptureFilter, params: unknown[]): string {
  const clauses: string[] = [];
  if (filter.since) {
    params.push(filter.since);
    clauses.push(`c.confirmed_at >= $${params.length}`);
  }
  if (filter.until) {
    params.push(filter.until);
    clauses.push(`c.confirmed_at <= $${params.length}`);
  }
  if (filter.bonding_number != null) {
    params.push(filter.bonding_number);
    clauses.push(`c.bonding_number = $${params.length}`);
  }
  if (filter.lot_location != null) {
    params.push(filter.lot_location);
    clauses.push(`COALESCE(c.lot_location, '') = $${params.length}`);
  }
  if (filter.lot_id != null) {
    params.push(filter.lot_id);
    clauses.push(`c.lot_id = $${params.length}`);
  }
  if (filter.mode != null) {
    params.push(filter.mode);
    clauses.push(`c.mode = $${params.length}`);
  }
  return clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
}

/** pg returns `timestamp` as a JS Date; consumers expect ISO strings. */
function isoOrNull(d: Date | string | null | undefined): string {
  if (d == null) return "";
  if (typeof d === "string") return d;
  return d.toISOString();
}

export async function recentCaptures(
  filter: CaptureFilter = {},
): Promise<Capture[]> {
  const limit = filter.limit ?? 50;
  const offset = filter.offset ?? 0;

  const params: unknown[] = [];
  const where = applyFilter(filter, params);
  params.push(limit);
  const limitIdx = params.length;
  params.push(offset);
  const offsetIdx = params.length;

  // CTE picks the page of capture_ids first, then JOINs in files only for
  // those rows.
  const sqlText = `
    WITH paged AS (
      SELECT capture_id
      FROM captures c
      ${where}
      ORDER BY c.confirmed_at DESC, c.capture_id
      LIMIT $${limitIdx} OFFSET $${offsetIdx}
    )
    SELECT c.*, f.slot, f.fused_path, f.fused_name,
           f.size_bytes AS file_size_bytes, f.sha256 AS file_sha256
    FROM captures c
    INNER JOIN paged p ON p.capture_id = c.capture_id
    LEFT JOIN capture_files f ON f.capture_id = c.capture_id
    ORDER BY c.confirmed_at DESC, c.capture_id, f.id;
  `;

  const result = await getPool().query<JoinedRow>(sqlText, params);
  const rows = result.rows;

  const grouped = new Map<string, Capture>();
  const order: string[] = [];

  for (const r of rows) {
    let cap = grouped.get(r.capture_id);
    if (!cap) {
      cap = {
        capture_id: r.capture_id,
        confirmed_at: isoOrNull(r.confirmed_at),
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
    // raw_lot_info is JSONB → pg already returns an object; parse only if a
    // row came back as a plain string.
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

export async function countCaptures(
  filter: CaptureFilter = {},
): Promise<number> {
  const params: unknown[] = [];
  const where = applyFilter(filter, params);
  const result = await getPool().query<{ n: number }>(
    `SELECT COUNT(*)::int AS n FROM captures c ${where}`,
    params,
  );
  return result.rows[0]?.n ?? 0;
}

/** Compute today/week/month/total counts in a single trip via SQL. */
export async function bucketCounts(
  now: Date = new Date(),
): Promise<BucketCounts> {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  const weekEnd = new Date(weekStart);
  weekEnd.setDate(weekStart.getDate() + 7);
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);

  const result = await getPool().query<{
    today: number | null;
    week: number | null;
    month: number | null;
    total: number;
  }>(
    `
    SELECT
      SUM(CASE WHEN confirmed_at >= $1 AND confirmed_at < $2 THEN 1 ELSE 0 END)::int AS today,
      SUM(CASE WHEN confirmed_at >= $3 AND confirmed_at < $4 THEN 1 ELSE 0 END)::int AS week,
      SUM(CASE WHEN confirmed_at >= $5 AND confirmed_at < $2 THEN 1 ELSE 0 END)::int AS month,
      COUNT(*)::int AS total
    FROM captures
  `,
    [today, tomorrow, weekStart, weekEnd, monthStart],
  );
  const row = result.rows[0];
  return {
    today: row?.today ?? 0,
    week: row?.week ?? 0,
    month: row?.month ?? 0,
    total: row?.total ?? 0,
  };
}

export async function lotCaptures(lotId: string): Promise<Capture[]> {
  return recentCaptures({ lot_id: lotId, limit: 500 });
}

export async function allLots(limit = 200): Promise<LotSummary[]> {
  const result = await getPool().query<{
    lot_id: string;
    last_confirmed_at: Date;
    capture_count: number;
  }>(
    `
    SELECT lot_id,
           MAX(confirmed_at) AS last_confirmed_at,
           COUNT(*)::int     AS capture_count
    FROM captures
    GROUP BY lot_id
    ORDER BY last_confirmed_at DESC
    LIMIT $1
  `,
    [limit],
  );
  return result.rows.map((r) => ({
    lot_id: r.lot_id,
    last_confirmed_at: isoOrNull(r.last_confirmed_at),
    capture_count: r.capture_count,
  }));
}
