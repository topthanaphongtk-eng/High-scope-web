# High Scope — Web Monitor

Web dashboard + central database schema for the **High Scope Capture**
QC stations. Read-only view of bond-ball measurements coming from the
desktop application; designed to run on a VM and read the SAME database
all stations write to.

> The PyQt6 desktop application that captures and writes the data lives
> in a separate repository.

## Layout

```
.
├── BRANCH_README.md                    sync workflow with the desktop repo
├── db/
│   ├── README.md                       schema reference + import workflow
│   ├── schema_mssql.sql                MS SQL Server DDL
│   └── schema_sqlite.sql               SQLite DDL (what the desktop builds)
└── web-deploy/
    ├── README.md                       VM setup + production WSGI
    ├── run_web.py                      entry point
    ├── requirements-web.txt            Flask + Pillow + PyYAML
    ├── web/                            Flask app + Jinja templates
    │   ├── server.py                   routes + JSON API
    │   └── templates/                  dashboard / lot detail / bonding trend
    └── app/services/measurement_db.py  DB reader (SQLite-backed)
```

## Quick start (VM)

```bash
git clone https://github.com/topthanaphongtk-eng/High-scope-web.git
cd High-scope-web/web-deploy

python -m pip install -r requirements-web.txt

# point at the central DB + share folder
export MEASUREMENT_DB="//fileserver/share/_db/measurements.db"
export SHARE_ROOT="//fileserver/share/Picture high"

python run_web.py --host 0.0.0.0 --port 8080
```

Open `http://<vm-ip>:8080` from any operator browser.

See [`web-deploy/README.md`](web-deploy/README.md) for production-WSGI
options (waitress / gunicorn) and firewall rules.

## Pages

| Route | Shows |
|---|---|
| `/` | Dashboard — stats cards, recent LOTs, bonding × machine list, filter bar |
| `/lot/<lot_id>` | Per-LOT detail — every session, full measurement table, image previews |
| `/bonding/<num>?machine=...` | Trend chart (Ball d + GAP min) for bonding × machine with 3σ UCL/LCL |
| `/api/measurements` | JSON listing — `?since=&until=&bonding=&machine=&limit=` |
| `/api/bondings` | Bonding × machine pairs with counts + last seen |
| `/api/lots`, `/api/trend/<num>` | LOT summary / trend stats JSON |

## Central database

Run [`db/schema_mssql.sql`](db/schema_mssql.sql) against your SQL Server
instance to create the `lot_sessions` + `measurements` tables, indices,
and the `v_measurements_full` / `v_lot_summary` views.

[`db/README.md`](db/README.md) documents every column and the BULK
INSERT workflow for seeding from CSV.

The web layer currently reads SQLite — see `BRANCH_README.md` for the
plan to swap in a `pyodbc`-backed adapter when the team is ready to move
off SQLite.

## Updating this repo

This repo's content is generated from the desktop project's `web-deploy/`
and `db/` folders on each release. See `BRANCH_README.md` for the sync
recipe.
