# High Scope Capture — Web Monitor (VM deploy bundle)

Read-only web view of the QC measurements DB. Reads the SAME database the
desktop app writes to. No write paths from the web side — operators write
through the desktop application.

## What's in this folder

```
web-deploy/
├── run_web.py                 entry point (python run_web.py --port 8080)
├── requirements-web.txt       minimum deps (Flask, Pillow, PyYAML)
├── web/                       Flask app + Jinja templates
│   ├── server.py
│   └── templates/             dashboard, lot detail, bonding trend, base
└── app/services/
    └── measurement_db.py      SQLite reader (same module the desktop uses)
```

No PyQt6 / OpenCV / matplotlib needed on the VM.

## Setup on the VM

```bash
# 1. Python 3.10+ required.
python -m pip install -r requirements-web.txt

# 2. Tell the server where to read DB + share folder.
#    Linux:
export MEASUREMENT_DB=/mnt/share/_db/measurements.db
export SHARE_ROOT="/mnt/share/Picture high"
#    Windows VM (PowerShell):
$env:MEASUREMENT_DB = "\\fileserver\share\_db\measurements.db"
$env:SHARE_ROOT     = "\\fileserver\share\Picture high"

# 3. Run.
python run_web.py --host 0.0.0.0 --port 8080
```

Open `http://<vm-ip>:8080` from any operator browser.

### Production-grade serving (optional)

The Flask dev server is fine for ≤ 10 concurrent users. For more, use a
proper WSGI server:

```bash
pip install waitress
python -m waitress --host=0.0.0.0 --port=8080 web.server:app
```

Or `gunicorn` on Linux. Or run behind nginx + Let's Encrypt for HTTPS.

### Firewall

```bash
# Linux (ufw)
sudo ufw allow 8080/tcp
# Windows VM
netsh advfirewall firewall add rule name="HighScope Monitor" dir=in action=allow protocol=TCP localport=8080
```

## Where data comes from

Desktop app on each station writes:
1. **TIFF files** + sidecar JSON → `{shared_root}/YYYY/MM/{lot_id}/`
2. **Measurement rows** → SQLite DB at `storage.db_path` (default `./logs/measurements.db`)
3. **Per-session JSON** → `{shared_root}/YYYY/MM/{lot_id}/_records/{uuid}.json`

For the web to see ALL stations, point every desktop's `db_path` AND the
web's `MEASUREMENT_DB` at the SAME file (commonly on the share folder).

## Switching to SQL Server

This bundle currently reads SQLite. The schema in `../db/schema_mssql.sql`
is the SQL Server equivalent — when the team is ready to move off SQLite:

1. Run `db/schema_mssql.sql` against the target SQL Server.
2. Bulk-import the CSVs from `db/exports/` (see `db/README.md`).
3. Replace `app/services/measurement_db.py` with a `pyodbc`-backed adapter
   using the same method names (`history_for_bonding`, `export_json`, …).

The web layer is decoupled from the engine: only `MeasurementDB`'s public
methods are called, so swapping the backing store is a localised change.
