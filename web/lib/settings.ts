import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import type { PoolConfig } from "pg";

const ROOT = path.resolve(process.cwd(), "..");

interface YamlSettings {
  storage?: { shared_root?: string };
  postgres?: {
    host?: string;
    port?: number;
    database?: string;
    user?: string;
    password?: string;
    sslmode?: string;
  };
}

function loadYaml(): YamlSettings {
  const file = path.join(ROOT, "config", "settings.yaml");
  if (!fs.existsSync(file)) return {};
  try {
    const parsed = yaml.load(fs.readFileSync(file, "utf-8"));
    return (parsed && typeof parsed === "object" ? parsed : {}) as YamlSettings;
  } catch (err) {
    console.error("failed to read settings.yaml:", err);
    return {};
  }
}

const yamlCfg = loadYaml();

export const SHARE_ROOT = path.resolve(
  process.env.SHARE_ROOT || yamlCfg.storage?.shared_root || ".",
);

let cachedPgConfig: PoolConfig | null = null;

/**
 * Build (and validate) the PostgreSQL connection config on first use.
 *
 * Validation is deferred to call time — importing this module must never
 * throw. `next build` imports every route module to collect page data, and
 * DB-less routes (e.g. /image, which only needs SHARE_ROOT) must load even
 * when DB config is absent. Mirrors the desktop app, whose CaptureDB also
 * defers its connection check so the GUI can open with incomplete settings.
 *
 * Reads the standard libpq env vars (PGHOST, PGPORT, ...) first, then falls
 * back to config/settings.yaml `postgres.*`.
 */
export function getPgConfig(): PoolConfig {
  if (cachedPgConfig) return cachedPgConfig;

  const host = process.env.PGHOST || yamlCfg.postgres?.host;
  const database = process.env.PGDATABASE || yamlCfg.postgres?.database;

  if (!host || !database) {
    throw new Error(
      "PGHOST and PGDATABASE must be set (env or config/settings.yaml postgres.*)",
    );
  }

  const sslmode =
    process.env.PGSSLMODE || yamlCfg.postgres?.sslmode || "prefer";
  const ssl = /^(require|verify-ca|verify-full)$/.test(sslmode)
    ? { rejectUnauthorized: sslmode === "verify-full" }
    : false;

  cachedPgConfig = {
    host,
    database,
    user: process.env.PGUSER || yamlCfg.postgres?.user,
    password: process.env.PGPASSWORD || yamlCfg.postgres?.password,
    port: Number(process.env.PGPORT) || yamlCfg.postgres?.port || 5432,
    ssl,
    max: 10,
    idleTimeoutMillis: 30_000,
  };

  return cachedPgConfig;
}
