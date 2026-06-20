/* =====================================================================
   High Scope Capture — PostgreSQL schema (capture-only)
   ----------------------------------------------------------------------
   The desktop stations (psycopg2) and the Next.js web monitor (pg) share
   one central PostgreSQL database. Neither app creates tables at runtime;
   they only read/write existing ones — run this script once on the server.

   Type mapping from the previous SQL Server schema:
     • UUID          ← UNIQUEIDENTIFIER   (client-generated uuid4)
     • TIMESTAMP(3)  ← DATETIME2(3)       (naive local time, no tz)
     • VARCHAR(n)    ← NVARCHAR(n)        (PostgreSQL is UTF-8 throughout)
     • JSONB         ← NVARCHAR(MAX)      (raw_lot_info — queryable JSON)
     • IDENTITY      ← IDENTITY(1,1)

   Idempotent — safe to re-run.

   Apply:  psql -h MTH-dk-b12416 -U highscope -d highscope -f db/schema_postgres.sql
   ===================================================================== */

-- =====================================================================
-- captures: one row per Confirm & Save action.
-- =====================================================================
CREATE TABLE IF NOT EXISTS captures (
    capture_id      UUID         PRIMARY KEY,           -- client-generated (uuid4)
    confirmed_at    TIMESTAMP(3) NOT NULL,              -- naive local time
    lot_id          VARCHAR(64)  NOT NULL,
    bonding_number  VARCHAR(64),
    lot_location    VARCHAR(64),                        -- machine / station from MES
    mpc             VARCHAR(64),
    package         VARCHAR(64),
    qs              VARCHAR(64),
    operator_badge  VARCHAR(32)  NOT NULL,
    hostname        VARCHAR(128),
    app_version     VARCHAR(32),
    mode            VARCHAR(16)  NOT NULL,              -- 'mode1' | 'mode2'
    raw_lot_info    JSONB                               -- JSON of full LotDetail
);

CREATE INDEX IF NOT EXISTS ix_captures_lot_date
    ON captures (lot_id, confirmed_at DESC);
CREATE INDEX IF NOT EXISTS ix_captures_bonding
    ON captures (bonding_number, lot_location, confirmed_at DESC);
CREATE INDEX IF NOT EXISTS ix_captures_date
    ON captures (confirmed_at DESC);

-- =====================================================================
-- capture_files: one row per fused image saved (Mode 1 -> 1 row, Mode 2 -> 3).
-- =====================================================================
CREATE TABLE IF NOT EXISTS capture_files (
    id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    capture_id  UUID         NOT NULL REFERENCES captures(capture_id),
    slot        VARCHAR(32)  NOT NULL,                  -- 'image' | 'Ball' | 'Pad' | 'Weld'
    fused_path  VARCHAR(512) NOT NULL,
    fused_name  VARCHAR(256) NOT NULL,
    size_bytes  BIGINT,
    sha256      VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS ix_capture_files_capture
    ON capture_files (capture_id);
