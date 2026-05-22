# High Scope Capture — Web Monitor (Next.js)

Read-only web view of `captures.db` — same database the desktop PyQt app
writes to. Operators write through the desktop app; this server only reads.

Ported from Flask to Next.js so it can deploy on hosts without a Python
runtime. Behaviour matches the Flask version 1:1.

## Stack

- Next.js 15 (App Router, TypeScript, React 19)
- **Node 22.5+ required** — uses the built-in `node:sqlite` (no native compile, no `better-sqlite3`)
- `sharp` for on-the-fly TIFF → JPEG conversion
- `js-yaml` for `config/settings.yaml`
- Tailwind v3 (proper toolchain — config in [tailwind.config.ts](./tailwind.config.ts))
- Inter + JetBrains Mono via `next/font` (self-hosted, no CDN)

## Setup

```bash
cd web
npm install
npm run dev        # http://localhost:3000
```

If you see `node:sqlite is an experimental feature and might change at any time`,
your Node version still flag-gates it. Run with:

```powershell
$env:NODE_OPTIONS = "--experimental-sqlite"
npm run dev
```

(Stable in Node 24+, experimental in Node 22.5–23.x.)

## Configuration

Same env vars as the Flask app:

```bash
# Linux / WSL
export CAPTURE_DB=/mnt/share/_db/captures.db
export SHARE_ROOT="/mnt/share/Picture high"

# Windows (PowerShell)
$env:CAPTURE_DB = "\\fileserver\share\_db\captures.db"
$env:SHARE_ROOT = "\\fileserver\share\Picture high"
```

Falls back to `config/settings.yaml` (`storage.db_path`, `storage.shared_root`)
in the repo root, then to `logs/captures.db` and `.`.

## Production

```bash
npm run build
npm run start            # binds 0.0.0.0:3000 by default
```

Override host/port via env:
```bash
PORT=8080 HOSTNAME=0.0.0.0 npm run start
```

### Firewall

```bash
# Linux
sudo ufw allow 3000/tcp
# Windows
netsh advfirewall firewall add rule name="HighScope Monitor" dir=in action=allow protocol=TCP localport=3000
```

### Behind a reverse proxy

`next start` is fine for ≤ a few hundred users. For HTTPS / multi-instance,
front it with nginx or IIS reverse proxy:

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Routes

| URL | Purpose |
|---|---|
| `/` | Dashboard — hero counts + filterable LOT gallery |
| `/lot/<lot_id>` | All captures for a single LOT |
| `/bonding/<num>?machine=<m>` | Captures for a bonding × machine pair |
| `/image?path=<rel>` | TIFF/PNG proxy from `SHARE_ROOT` (TIFF → JPEG on the fly) |
| `/api/lots` | JSON list of distinct LOTs |
| `/api/captures` | JSON list of captures (filterable: `since`, `until`, `bonding`, `machine`, `lot`, `mode`, `limit`) |

## Source layout

```
web/
├── app/                         App Router pages + API routes
│   ├── layout.tsx               base.html port
│   ├── globals.css              copy of the original styles.css
│   ├── page.tsx                 dashboard
│   ├── lot/[lotId]/page.tsx
│   ├── bonding/[bonding]/page.tsx
│   ├── image/route.ts           TIFF → JPEG via sharp
│   └── api/{lots,captures}/route.ts
├── components/                  CaptureCard, FilterBar, HeroCounts
├── lib/
│   ├── capture-db.ts            better-sqlite3 wrapper (read-only)
│   ├── settings.ts              yaml + ENV precedence
│   ├── format.ts                fmtDt, parseDate, parseUntil, toImageUrl
│   ├── decorate.ts              attach image_rel to capture files
│   └── types.ts
├── package.json
├── tsconfig.json
└── next.config.mjs
```

## Where data comes from

Each desktop station writes:
1. **Fused TIFF** + sidecar JSON → `{shared_root}/YYYY/MM/{lot_id}/`
2. **Capture rows** → SQLite at `storage.db_path`
3. **Per-capture JSON** → `{shared_root}/YYYY/MM/{lot_id}/_records/{uuid}.json`

For the web to see all stations, point every desktop's `db_path` AND the
web's `CAPTURE_DB` at the same shared file.

## Switching to SQL Server

The web side uses only `recentCaptures`, `lotCaptures`, `allLots` from
`lib/capture-db.ts`. Swap that module for an `mssql` (`tedious`) adapter
that returns the same shapes — no other files need to change.
