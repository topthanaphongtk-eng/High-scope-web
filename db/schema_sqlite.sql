/* =====================================================================
   High Scope Capture — SQLite reference schema (capture-only)
   ----------------------------------------------------------------------
   This is what `app/services/capture_db.py` builds at runtime. It is
   provided here purely for review / version-control of the DB design.
   ===================================================================== */

CREATE TABLE IF NOT EXISTS captures (
    capture_id      TEXT PRIMARY KEY,            -- UUID per Confirm
    confirmed_at    TEXT NOT NULL,               -- ISO 8601
    lot_id          TEXT NOT NULL,
    bonding_number  TEXT,
    lot_location    TEXT,                        -- machine / station from MES
    mpc             TEXT,
    package         TEXT,
    qs              TEXT,
    operator_badge  TEXT NOT NULL,
    hostname        TEXT,
    app_version     TEXT,
    mode            TEXT NOT NULL,               -- 'mode1' | 'mode2'
    raw_lot_info    TEXT                         -- JSON dump of full LotDetail
);

CREATE INDEX IF NOT EXISTS idx_captures_lot
    ON captures (lot_id, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_captures_bonding
    ON captures (bonding_number, lot_location, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_captures_date
    ON captures (confirmed_at);


CREATE TABLE IF NOT EXISTS capture_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      TEXT NOT NULL,               -- FK → captures.capture_id
    slot            TEXT NOT NULL,               -- 'image' | 'Ball' | 'Pad' | 'Weld'
    fused_path      TEXT NOT NULL,
    fused_name      TEXT NOT NULL,
    size_bytes      INTEGER,
    sha256          TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_capture
    ON capture_files (capture_id);
