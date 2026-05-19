/* =====================================================================
   High Scope Capture — MS SQL Server schema
   ----------------------------------------------------------------------
   Mirrors the SQLite layout used by the desktop app, with adjustments
   for SQL Server semantics:

     • IDENTITY(1,1)  instead of  AUTOINCREMENT
     • DATETIME2(3)   instead of  TEXT (ISO-8601)
     • NVARCHAR(...)  for Unicode-safe TEXT
     • NVARCHAR(MAX)  for the JSON columns (raw_lot_info, extra_json)
     • View built after tables (same as SQLite, but uses GO batches)

   Run this script in SSMS (or sqlcmd / Azure Data Studio) against the
   target database. It is idempotent — safe to re-run.
   ===================================================================== */

-- Pick the target DB. Adjust the name to your environment.
-- USE [HighScopeCapture];
-- GO

-- =====================================================================
-- Sessions: one row per Confirm & Save action.
-- =====================================================================
IF OBJECT_ID(N'dbo.lot_sessions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.lot_sessions (
        session_id        UNIQUEIDENTIFIER NOT NULL  CONSTRAINT PK_lot_sessions PRIMARY KEY,
        confirmed_at      DATETIME2(3)     NOT NULL,
        lot_id            NVARCHAR(64)     NOT NULL,
        bonding_number    NVARCHAR(64)     NULL,
        lot_location      NVARCHAR(64)     NULL,        -- machine / station from MES
        mpc               NVARCHAR(64)     NULL,
        package           NVARCHAR(64)     NULL,
        qs                NVARCHAR(64)     NULL,
        operator_badge    NVARCHAR(32)     NOT NULL,
        hostname          NVARCHAR(128)    NULL,
        app_version       NVARCHAR(32)     NULL,
        n_locations       INT              NOT NULL,
        n_pads            INT              NOT NULL,
        raw_lot_info      NVARCHAR(MAX)    NULL          -- JSON of full LotDetail
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_lot_sessions_lot_date'
               AND object_id=OBJECT_ID('dbo.lot_sessions'))
    CREATE INDEX IX_lot_sessions_lot_date
        ON dbo.lot_sessions (lot_id, confirmed_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_lot_sessions_bonding'
               AND object_id=OBJECT_ID('dbo.lot_sessions'))
    CREATE INDEX IX_lot_sessions_bonding
        ON dbo.lot_sessions (bonding_number, lot_location, confirmed_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_lot_sessions_date'
               AND object_id=OBJECT_ID('dbo.lot_sessions'))
    CREATE INDEX IX_lot_sessions_date
        ON dbo.lot_sessions (confirmed_at DESC);
GO

-- =====================================================================
-- Measurements: one row per pad detected. Many-to-one to lot_sessions.
-- Most analytic queries hit this table directly via the indices below.
-- =====================================================================
IF OBJECT_ID(N'dbo.measurements', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.measurements (
        id                 BIGINT           IDENTITY(1,1)
                                             CONSTRAINT PK_measurements PRIMARY KEY,
        session_id         UNIQUEIDENTIFIER NULL,
        confirmed_at       DATETIME2(3)     NOT NULL,
        lot_id             NVARCHAR(64)     NOT NULL,
        bonding_number     NVARCHAR(64)     NOT NULL,
        lot_location       NVARCHAR(64)     NULL,
        mpc                NVARCHAR(64)     NULL,
        package            NVARCHAR(64)     NULL,
        qs                 NVARCHAR(64)     NULL,
        operator_badge     NVARCHAR(32)     NOT NULL,

        location           NVARCHAR(8)      NOT NULL,    -- TL / TR / BL / BR
        pad_index          INT              NOT NULL,    -- 1..N within the location

        pad_w_um           FLOAT            NULL,
        pad_h_um           FLOAT            NULL,
        ball_d_um          FLOAT            NULL,
        gap_min_um         FLOAT            NULL,
        gap_mean_um        FLOAT            NULL,

        confidence         NVARCHAR(16)     NULL,        -- high / medium / low
        pixel_size_um      FLOAT            NULL,

        source_ball_path   NVARCHAR(512)    NULL,        -- operator's drop
        source_pad_path    NVARCHAR(512)    NULL,
        stored_ball_path   NVARCHAR(512)    NULL,        -- final share-folder path
        stored_pad_path    NVARCHAR(512)    NULL,

        extra_json         NVARCHAR(MAX)    NULL,        -- raw PadMeasurement.to_dict()

        CONSTRAINT FK_measurements_session
            FOREIGN KEY (session_id) REFERENCES dbo.lot_sessions(session_id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_measurements_bonding'
               AND object_id=OBJECT_ID('dbo.measurements'))
    CREATE INDEX IX_measurements_bonding
        ON dbo.measurements (bonding_number, lot_location, confirmed_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_measurements_lot'
               AND object_id=OBJECT_ID('dbo.measurements'))
    CREATE INDEX IX_measurements_lot
        ON dbo.measurements (lot_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_measurements_date'
               AND object_id=OBJECT_ID('dbo.measurements'))
    CREATE INDEX IX_measurements_date
        ON dbo.measurements (confirmed_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_measurements_session'
               AND object_id=OBJECT_ID('dbo.measurements'))
    CREATE INDEX IX_measurements_session
        ON dbo.measurements (session_id);
GO

-- =====================================================================
-- View: every measurement joined with its session-level context.
-- Web / BI tools can SELECT * FROM v_measurements_full WHERE …
-- without remembering which columns live where.
-- =====================================================================
IF OBJECT_ID(N'dbo.v_measurements_full', N'V') IS NOT NULL
    DROP VIEW dbo.v_measurements_full;
GO

CREATE VIEW dbo.v_measurements_full AS
SELECT
    m.id, m.session_id, m.confirmed_at,
    m.lot_id, m.bonding_number, m.lot_location,
    m.mpc, m.package, m.qs, m.operator_badge,
    s.hostname, s.app_version,
    m.location, m.pad_index,
    m.pad_w_um, m.pad_h_um,
    m.ball_d_um, m.gap_min_um, m.gap_mean_um,
    m.confidence, m.pixel_size_um,
    m.source_ball_path, m.source_pad_path,
    m.stored_ball_path, m.stored_pad_path,
    m.extra_json,
    s.raw_lot_info
FROM dbo.measurements AS m
LEFT JOIN dbo.lot_sessions AS s
       ON s.session_id = m.session_id;
GO

-- =====================================================================
-- (Optional) Aggregated trend view — one row per LOT, mean across the 4
-- locations. Useful for reporting / Power BI without re-aggregating in
-- the client every time.
-- =====================================================================
IF OBJECT_ID(N'dbo.v_lot_summary', N'V') IS NOT NULL
    DROP VIEW dbo.v_lot_summary;
GO

CREATE VIEW dbo.v_lot_summary AS
SELECT
    s.session_id,
    s.confirmed_at,
    s.lot_id,
    s.bonding_number,
    s.lot_location,
    s.mpc,
    s.package,
    s.operator_badge,
    s.n_locations,
    s.n_pads,
    AVG(m.ball_d_um)   AS ball_d_avg_um,
    MIN(m.ball_d_um)   AS ball_d_min_um,
    MAX(m.ball_d_um)   AS ball_d_max_um,
    AVG(m.gap_min_um)  AS gap_min_avg_um,
    MIN(m.gap_min_um)  AS gap_min_min_um,
    AVG(m.gap_mean_um) AS gap_mean_avg_um
FROM dbo.lot_sessions AS s
LEFT JOIN dbo.measurements AS m
       ON m.session_id = s.session_id
GROUP BY
    s.session_id, s.confirmed_at, s.lot_id,
    s.bonding_number, s.lot_location, s.mpc, s.package,
    s.operator_badge, s.n_locations, s.n_pads;
GO
