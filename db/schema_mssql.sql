/* =====================================================================
   High Scope Capture — MS SQL Server schema (capture-only)
   ----------------------------------------------------------------------
   Mirrors the SQLite layout used by the desktop app, with adjustments
   for SQL Server semantics:

     • IDENTITY(1,1)  instead of  AUTOINCREMENT
     • DATETIME2(3)   instead of  TEXT (ISO-8601)
     • NVARCHAR(...)  for Unicode-safe TEXT
     • NVARCHAR(MAX)  for the JSON column (raw_lot_info)

   Run this script in SSMS (or sqlcmd / Azure Data Studio) against the
   target database. It is idempotent — safe to re-run.
   ===================================================================== */

-- USE [HighScopeCapture];
-- GO

-- =====================================================================
-- captures: one row per Confirm & Save action.
-- =====================================================================
IF OBJECT_ID(N'dbo.captures', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.captures (
        capture_id        UNIQUEIDENTIFIER NOT NULL  CONSTRAINT PK_captures PRIMARY KEY,
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
        mode              NVARCHAR(16)     NOT NULL,    -- 'mode1' | 'mode2'
        raw_lot_info      NVARCHAR(MAX)    NULL          -- JSON of full LotDetail
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_captures_lot_date'
               AND object_id=OBJECT_ID('dbo.captures'))
    CREATE INDEX IX_captures_lot_date
        ON dbo.captures (lot_id, confirmed_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_captures_bonding'
               AND object_id=OBJECT_ID('dbo.captures'))
    CREATE INDEX IX_captures_bonding
        ON dbo.captures (bonding_number, lot_location, confirmed_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_captures_date'
               AND object_id=OBJECT_ID('dbo.captures'))
    CREATE INDEX IX_captures_date
        ON dbo.captures (confirmed_at DESC);
GO

-- =====================================================================
-- capture_files: one row per fused image saved (Mode 1 → 1 row, Mode 2 → 3).
-- =====================================================================
IF OBJECT_ID(N'dbo.capture_files', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.capture_files (
        id                BIGINT           IDENTITY(1,1)
                                            CONSTRAINT PK_capture_files PRIMARY KEY,
        capture_id        UNIQUEIDENTIFIER NOT NULL,
        slot              NVARCHAR(32)     NOT NULL,    -- 'image' | 'Ball' | 'Pad' | 'Weld'
        fused_path        NVARCHAR(512)    NOT NULL,
        fused_name        NVARCHAR(256)    NOT NULL,
        size_bytes        BIGINT           NULL,
        sha256            NVARCHAR(64)     NULL,

        CONSTRAINT FK_capture_files_capture
            FOREIGN KEY (capture_id) REFERENCES dbo.captures(capture_id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_capture_files_capture'
               AND object_id=OBJECT_ID('dbo.capture_files'))
    CREATE INDEX IX_capture_files_capture
        ON dbo.capture_files (capture_id);
GO
