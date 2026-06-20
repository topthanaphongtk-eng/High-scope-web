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

-- =====================================================================
-- QC MODE  (WEB-written — the desktop never touches these two tables.
-- The web only references captures(capture_id) via a read-only FK.)
-- Requires PostgreSQL 12+ for the GENERATED ... STORED column.
-- =====================================================================

-- qc_operators: badge-only login directory (no password by design).
-- Soft-disable via `active` — never hard-delete (reviews FK these rows).
CREATE TABLE IF NOT EXISTS qc_operators (
    badge_number  VARCHAR(32)  PRIMARY KEY,   -- same domain as captures.operator_badge
    full_name     VARCHAR(255) NOT NULL,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP(3) NOT NULL        -- set by app (Node local time)
);

-- qc_reviews: one CURRENT verdict per capture (re-grade = UPSERT on capture_id).
-- 3 items each PASS|REJECT + optional note. overall_verdict is GENERATED so the
-- rollup rule lives in the DB and cannot drift. package / confirmed_at are NOT
-- copied here — the summary JOINs captures (immutable once confirmed).
CREATE TABLE IF NOT EXISTS qc_reviews (
    id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    capture_id       UUID         NOT NULL REFERENCES captures(capture_id),
    badge_number     VARCHAR(32)  NOT NULL REFERENCES qc_operators(badge_number),
    reviewed_at      TIMESTAMP(3) NOT NULL,        -- set by app (Node local time)

    ball_size        VARCHAR(8)   NOT NULL CHECK (ball_size   IN ('PASS','REJECT')),
    ball_size_note   VARCHAR(512),
    pad_bond         VARCHAR(8)   NOT NULL CHECK (pad_bond    IN ('PASS','REJECT')),
    pad_bond_note    VARCHAR(512),
    weld_damage      VARCHAR(8)   NOT NULL CHECK (weld_damage IN ('PASS','REJECT')),
    weld_damage_note VARCHAR(512),

    overall_verdict  VARCHAR(8)
        GENERATED ALWAYS AS (
            CASE WHEN ball_size = 'REJECT' OR pad_bond = 'REJECT' OR weld_damage = 'REJECT'
                 THEN 'REJECT' ELSE 'PASS' END
        ) STORED,

    CONSTRAINT uq_qc_reviews_capture UNIQUE (capture_id)   -- also indexes capture_id
);

-- Operator audit trail / "my recent reviews".
CREATE INDEX IF NOT EXISTS ix_qc_reviews_badge
    ON qc_reviews (badge_number, reviewed_at DESC);

-- qc_acknowledgements: audit log of operators accepting the Visual Aid QC
-- criteria. One row per acceptance (operators re-accept every login).
CREATE TABLE IF NOT EXISTS qc_acknowledgements (
    id            BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    badge_number  VARCHAR(32)  NOT NULL REFERENCES qc_operators(badge_number),
    accepted_at   TIMESTAMP(3) NOT NULL        -- set by app (Node local time)
);

CREATE INDEX IF NOT EXISTS ix_qc_ack_badge
    ON qc_acknowledgements (badge_number, accepted_at DESC);
