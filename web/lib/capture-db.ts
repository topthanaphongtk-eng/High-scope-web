import sql from "mssql";
import { MSSQL_CONFIG } from "./settings";
import type {
  BucketCounts,
  Capture,
  CaptureFile,
  CaptureFilter,
  LotSummary,
} from "./types";

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
  raw_lot_info: string | null;
  slot: string | null;
  fused_path: string | null;
  fused_name: string | null;
  file_size_bytes: number | null;
  file_sha256: string | null;
}

let poolPromise: Promise<sql.ConnectionPool> | null = null;

/** Lazy, shared connection pool. mssql's pool internally manages many
 * connections — opening one per request is the wrong shape here. */
function getPool(): Promise<sql.ConnectionPool> {
  if (!poolPromise) {
    poolPromise = new sql.ConnectionPool(MSSQL_CONFIG)
      .connect()
      .catch((err) => {
        poolPromise = null;
        throw err;
      });
  }
  return poolPromise;
}

/** Bind filter clauses + params on a request. Shared by recentCaptures and
 * countCaptures so the WHERE shape stays in sync. */
function applyFilter(filter: CaptureFilter, request: sql.Request): string {
  const clauses: string[] = [];
  if (filter.since) {
    request.input("since", sql.DateTime2, filter.since);
    clauses.push("c.confirmed_at >= @since");
  }
  if (filter.until) {
    request.input("until_", sql.DateTime2, filter.until);
    clauses.push("c.confirmed_at <= @until_");
  }
  if (filter.bonding_number != null) {
    request.input("bonding_number", sql.NVarChar(64), filter.bonding_number);
    clauses.push("c.bonding_number = @bonding_number");
  }
  if (filter.lot_location != null) {
    request.input("lot_location", sql.NVarChar(64), filter.lot_location);
    clauses.push("ISNULL(c.lot_location, N'') = @lot_location");
  }
  if (filter.lot_id != null) {
    request.input("lot_id", sql.NVarChar(64), filter.lot_id);
    clauses.push("c.lot_id = @lot_id");
  }
  if (filter.mode != null) {
    request.input("mode", sql.NVarChar(16), filter.mode);
    clauses.push("c.mode = @mode");
  }
  return clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
}

/** SQL Server returns DATETIME2 as a JS Date; consumers expect ISO strings
 * (the field was originally TEXT in SQLite). Convert at the boundary. */
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
  const pool = await getPool();
  const request = pool.request();
  const where = applyFilter(filter, request);
  request.input("limit_", sql.Int, limit);
  request.input("offset_", sql.Int, offset);

  // CTE picks the page of capture_ids first, then JOINs in files only for
  // those rows. OFFSET/FETCH replaces SQLite's LIMIT/OFFSET.
  const sqlText = `
    WITH paged AS (
      SELECT capture_id
      FROM dbo.captures c
      ${where}
      ORDER BY c.confirmed_at DESC, c.capture_id
      OFFSET @offset_ ROWS FETCH NEXT @limit_ ROWS ONLY
    )
    SELECT c.*, f.slot, f.fused_path, f.fused_name,
           f.size_bytes AS file_size_bytes, f.sha256 AS file_sha256
    FROM dbo.captures c
    INNER JOIN paged p ON p.capture_id = c.capture_id
    LEFT JOIN dbo.capture_files f ON f.capture_id = c.capture_id
    ORDER BY c.confirmed_at DESC, c.capture_id, f.id;
  `;

  const result = await request.query<JoinedRow>(sqlText);
  const rows = result.recordset;

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
  const pool = await getPool();
  const request = pool.request();
  const where = applyFilter(filter, request);
  const result = await request.query<{ n: number }>(
    `SELECT COUNT(*) AS n FROM dbo.captures c ${where}`,
  );
  return result.recordset[0]?.n ?? 0;
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

  const pool = await getPool();
  const request = pool
    .request()
    .input("today", sql.DateTime2, today)
    .input("tomorrow", sql.DateTime2, tomorrow)
    .input("weekStart", sql.DateTime2, weekStart)
    .input("weekEnd", sql.DateTime2, weekEnd)
    .input("monthStart", sql.DateTime2, monthStart);

  const result = await request.query<{
    today: number | null;
    week: number | null;
    month: number | null;
    total: number;
  }>(`
    SELECT
      SUM(CASE WHEN confirmed_at >= @today      AND confirmed_at < @tomorrow THEN 1 ELSE 0 END) AS today,
      SUM(CASE WHEN confirmed_at >= @weekStart  AND confirmed_at < @weekEnd  THEN 1 ELSE 0 END) AS week,
      SUM(CASE WHEN confirmed_at >= @monthStart AND confirmed_at < @tomorrow THEN 1 ELSE 0 END) AS month,
      COUNT(*) AS total
    FROM dbo.captures
  `);
  const row = result.recordset[0];
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
  const pool = await getPool();
  const request = pool.request().input("limit_", sql.Int, limit);
  const result = await request.query<{
    lot_id: string;
    last_confirmed_at: Date;
    capture_count: number;
  }>(`
    SELECT TOP (@limit_)
           lot_id,
           MAX(confirmed_at) AS last_confirmed_at,
           COUNT(*)          AS capture_count
    FROM dbo.captures
    GROUP BY lot_id
    ORDER BY last_confirmed_at DESC
  `);
  return result.recordset.map((r) => ({
    lot_id: r.lot_id,
    last_confirmed_at: isoOrNull(r.last_confirmed_at),
    capture_count: r.capture_count,
  }));
}
