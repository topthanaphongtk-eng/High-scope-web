# High Scope Capture

Two-part QC system for wire-bond inspection:

- **Desktop capture app** (Python / PyQt) — runs on each operator station. Pairs Olympus STM 7 microscope captures with LOT data from the plant MES and files each image into a shared QC folder with a JSON sidecar. Records every Confirm event into `captures.db`.
- **Web monitor** (Next.js) — read-only image gallery served from any host with Node 22.5+. Reads the same `captures.db` so the team can browse captures by LOT / bonding / machine without touching the operator stations. See [web/README.md](web/README.md).

The Python desktop app is the only thing that **writes** to the DB. The web tier is purely read-only.

## How it works (desktop)

```
┌───────────────── PyQt GUI (this app) ─────────────────┐
│                                                        │
│  1.  Operator types LOT ID → Fetch                     │
│  2.  App calls MES SOAP `getDetailLotMES`              │
│  3.  Operator presses [Arm for capture]                │
│  4.  App starts watching D:\Auto save\ recursively     │
│  5.  Operator keeps using Olympus Stream normally      │
│      (Snap button → Stream auto-saves .tif)            │
│  6.  App detects the new .tif, parses OME-XML,         │
│      copies to shared folder with sidecar JSON         │
│  7.  Repeat 5–6 until [Disarm]                         │
└────────────────────────────────────────────────────────┘
```

## Setup (desktop)

1. **Install Python 3.12+** (already present on the target PCs).
2. **Install dependencies:**
   ```powershell
   python -m pip install -r requirements.txt
   ```
3. **Copy the example config:**
   ```powershell
   copy config\settings.example.yaml config\settings.yaml
   ```
4. **Edit `config\settings.yaml`** — in particular `storage.shared_root` must point at the shared QC folder (e.g. `//fileserver/qc-images`).
5. **Configure Olympus Stream** to auto-save `.tif` into `D:\Auto save\` (per-day subfolder `folder_YYYYMMDD` is expected and handled).

## Running (desktop)

```powershell
python main.py
```

Or specify a config:

```powershell
python main.py --config config\settings.yaml
```

## Web monitor (read-only gallery)

The web view lives in [web/](web/) — a Next.js App Router app, no Python.
It reads the same `captures.db` and serves TIFF previews from `SHARE_ROOT`
(TIFF → JPEG conversion happens on the fly via `sharp`).

Quick start on a server with **Node 22.5+**:

```bash
cd web
npm install
# Tell the server where to read the DB + share folder
export CAPTURE_DB="//fileserver/share/_db/captures.db"
export SHARE_ROOT="//fileserver/share/Picture high"
npm run build
npm run start                   # http://0.0.0.0:3000
```

Detailed deploy notes (firewall, reverse-proxy, env vars, troubleshooting)
are in [web/README.md](web/README.md).

## Output layout

```
<shared_root>\YYYY\MM\<LOT_ID>\
    <LOT_ID>_<YYYYMMDD_HHMMSS>_<hostname>_<seq>.tif
    <LOT_ID>_<YYYYMMDD_HHMMSS>_<hostname>_<seq>.json
```

The `.tif` is a byte-for-byte copy of the file Olympus saved — OME-XML metadata is preserved. The `.json` sidecar adds LOT context and a flattened subset of OME fields for quick search/filter.

## Project layout

```
main.py                  # desktop entry point (PyQt GUI)
requirements.txt         # Python deps for the desktop app

app/                     # ── Desktop capture app (Python) ──
    config.py            # pydantic settings loader
    models/
        lot.py           # LotDetail (from MES)
        capture.py       # OmeAcquisition + CaptureRecord
    services/
        lot_client.py    # zeep SOAP client (getDetailLotMES)
        omexml.py        # parse OME-XML from TIFF tag 270
        capture.py       # watchdog file watcher
        image_store.py   # atomic copy + sidecar writer
        capture_db.py    # SQLite writer (captures + capture_files)
    gui/
        main_window.py   # PyQt6 main window
    utils/
        logging.py

web/                     # ── Web monitor (Next.js / TypeScript) ──
    app/                 # App Router pages + route handlers
        page.tsx                    # / (dashboard)
        lot/[lotId]/page.tsx
        bonding/[bonding]/page.tsx
        image/route.ts              # TIFF → JPEG proxy
        api/{lots,captures}/route.ts
    components/          # CaptureCard, FilterBar, HeroCounts, Pagination
    lib/
        capture-db.ts    # node:sqlite reader (read-only)
        settings.ts      # yaml + ENV precedence
        format.ts        # date/path utilities
    package.json
    tailwind.config.ts

config/
    settings.example.yaml
db/
    schema_sqlite.sql    # canonical schema
    schema_mssql.sql     # SQL Server equivalent (future migration)
tests/
tools/                   # CSV export / backfill utilities
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Cannot reach MES server" at startup | WSDL URL unreachable — check the box is on the plant network |
| LOT shows red border, "LOT not found" | `Reply_Code != 0` returned by MES; message is from the server |
| TIFF saved but sidecar missing / crashes on parse | OME-XML malformed — file is still safe, just parse fails; check `logs/app.log` |
| Same file appears twice in the session list | Olympus rewrote the file; de-dupe is by path — if this recurs, inspect logs |
