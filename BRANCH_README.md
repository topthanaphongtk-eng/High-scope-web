# High Scope Capture — `web-only` branch

This branch carries **only** what the team needs to deploy the web monitor
on a VM and to set up the central database. The full desktop application
(PyQt6, OpenCV, file watcher, …) lives on the `main` branch.

## Layout

```
.
├── BRANCH_README.md                this file
├── db/
│   ├── README.md                   schema reference + import workflow
│   ├── schema_mssql.sql            MS SQL Server DDL  ← review this
│   └── schema_sqlite.sql           SQLite DDL (what the desktop builds at runtime)
└── web-deploy/
    ├── README.md                   VM setup steps
    ├── run_web.py                  entry point
    ├── requirements-web.txt        Flask + Pillow + PyYAML
    ├── web/                        Flask app + Jinja templates
    └── app/services/measurement_db.py    DB reader (SQLite-backed)
```

## Quick start for the VM team

```bash
# (on the VM)
git clone -b web-only <repo-url> highscope-monitor
cd highscope-monitor/web-deploy

python -m pip install -r requirements-web.txt

# point at the DB + share folder
export MEASUREMENT_DB="//fileserver/share/_db/measurements.db"
export SHARE_ROOT="//fileserver/share/Picture high"

python run_web.py --host 0.0.0.0 --port 8080
```

Open `http://<vm-ip>:8080` from any operator browser.

See [`web-deploy/README.md`](web-deploy/README.md) for production-WSGI
options (waitress / gunicorn) and firewall rules.

## Setting up the central database

Run [`db/schema_mssql.sql`](db/schema_mssql.sql) against your SQL Server
instance. The companion [`db/README.md`](db/README.md) documents every
column and the BULK INSERT workflow for seeding from the desktop's
SQLite export.

## Updating this branch

The branch is regenerated from `main` whenever the schema or web layer
changes. From `main`:

```bash
# (re)stage web-deploy/ from main (keeps it in sync with the live code)
git checkout main -- app/services/measurement_db.py
cp -r web/  web-deploy/web/
cp -r app/__init__.py app/services/__init__.py app/services/measurement_db.py web-deploy/app/services/

# push updated web-deploy + db to web-only
git switch web-only
git checkout main -- web-deploy/ db/
git commit -m "sync web-deploy + db from main"
git push origin web-only
```
