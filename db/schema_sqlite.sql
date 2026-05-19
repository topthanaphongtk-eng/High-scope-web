/* =====================================================================
   High Scope Capture — SQLite reference schema
   ----------------------------------------------------------------------
   This is what `app/services/measurement_db.py` builds at runtime. It is
   provided here purely for review / version-control of the DB design.
   The Python code keeps the canonical version (with online migrations);
   this file mirrors that for humans.
   ===================================================================== */

CREATE TABLE IF NOT EXISTS lot_sessions (
    session_id      TEXT PRIMARY KEY,            -- UUID per Confirm
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
    n_locations     INTEGER NOT NULL,
    n_pads          INTEGER NOT NULL,
    raw_lot_info    TEXT                         -- JSON dump of full LotDetail
);

CREATE INDEX IF NOT EXISTS idx_session_lot
    ON lot_sessions (lot_id, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_session_bonding
    ON lot_sessions (bonding_number, lot_location, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_session_date
    ON lot_sessions (confirmed_at);


CREATE TABLE IF NOT EXISTS measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,                        -- FK → lot_sessions.session_id
    confirmed_at    TEXT    NOT NULL,
    lot_id          TEXT    NOT NULL,
    bonding_number  TEXT    NOT NULL,
    lot_location    TEXT,
    mpc             TEXT,
    package         TEXT,
    qs              TEXT,
    operator_badge  TEXT    NOT NULL,

    location        TEXT    NOT NULL,            -- TL / TR / BL / BR
    pad_index       INTEGER NOT NULL,

    pad_w_um        REAL,
    pad_h_um        REAL,
    ball_d_um       REAL,
    gap_min_um      REAL,
    gap_mean_um     REAL,

    confidence      TEXT,
    pixel_size_um   REAL,

    source_ball_path TEXT,
    source_pad_path  TEXT,
    stored_ball_path TEXT,
    stored_pad_path  TEXT,

    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_bonding
    ON measurements (bonding_number, lot_location, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_lot
    ON measurements (lot_id);
CREATE INDEX IF NOT EXISTS idx_date
    ON measurements (confirmed_at);
CREATE INDEX IF NOT EXISTS idx_session
    ON measurements (session_id);


-- Convenience read view (joins session context).
DROP VIEW IF EXISTS v_measurements_full;
CREATE VIEW v_measurements_full AS
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
FROM measurements m
LEFT JOIN lot_sessions s ON s.session_id = m.session_id;
