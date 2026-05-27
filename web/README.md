# High Scope Capture — Web Monitor (Next.js)

Read-only web view of the central SQL Server DB (`schema_mssql.sql`) the
desktop PyQt app writes to. Operators write through the desktop app; this
server only reads.

## Stack

- Next.js 15 (App Router, TypeScript, React 19)
- `mssql` (tedious driver) — connection-pooled SQL Server client
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

The DB schema lives at [`db/schema_mssql.sql`](../db/schema_mssql.sql) — run
it once on the SQL Server before starting the web app.

## Configuration

Two things to point at: the SQL Server, and the TIFF share folder.

Drop a `web/.env.local` (gitignored) with:

```ini
# MSSQL connection
MSSQL_SERVER=sql.example.local        # required
MSSQL_DATABASE=HighScopeCapture       # required
MSSQL_USER=highscope_reader
MSSQL_PASSWORD=********
MSSQL_PORT=1433
MSSQL_ENCRYPT=true
MSSQL_TRUST_SERVER_CERT=true          # set false if the server has a trusted cert

# TIFF share root
SHARE_ROOT=\\fileserver\share\Picture high
```

Falls back to `config/settings.yaml` (`mssql.*`, `storage.shared_root`) in
the repo root if env vars aren't set.

The user only needs `SELECT` on `dbo.captures` and `dbo.capture_files`.

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
│   ├── capture-db.ts            mssql pool + read queries (async)
│   ├── settings.ts              yaml + ENV precedence; MSSQL_CONFIG
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
2. **Capture rows** → SQL Server (`dbo.captures` + `dbo.capture_files`)
3. **Per-capture JSON** → `{shared_root}/YYYY/MM/{lot_id}/_records/{uuid}.json`

All stations point at the same SQL Server; the web app sees the union.
