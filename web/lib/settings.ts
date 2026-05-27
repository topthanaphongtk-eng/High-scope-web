import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import type { config as MssqlConfig } from "mssql";

const ROOT = path.resolve(process.cwd(), "..");

interface YamlSettings {
  storage?: { shared_root?: string };
  mssql?: {
    server?: string;
    database?: string;
    user?: string;
    password?: string;
    port?: number;
    encrypt?: boolean;
    trust_server_certificate?: boolean;
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

function envBool(name: string, fallback: boolean): boolean {
  const v = process.env[name];
  if (v == null) return fallback;
  return /^(1|true|yes|on)$/i.test(v);
}

const server = process.env.MSSQL_SERVER || yamlCfg.mssql?.server;
const database = process.env.MSSQL_DATABASE || yamlCfg.mssql?.database;

if (!server || !database) {
  throw new Error(
    "MSSQL_SERVER and MSSQL_DATABASE must be set (env or config/settings.yaml mssql.*)",
  );
}

export const MSSQL_CONFIG: MssqlConfig = {
  server,
  database,
  user: process.env.MSSQL_USER || yamlCfg.mssql?.user,
  password: process.env.MSSQL_PASSWORD || yamlCfg.mssql?.password,
  port: Number(process.env.MSSQL_PORT) || yamlCfg.mssql?.port || 1433,
  options: {
    encrypt: envBool("MSSQL_ENCRYPT", yamlCfg.mssql?.encrypt ?? true),
    trustServerCertificate: envBool(
      "MSSQL_TRUST_SERVER_CERT",
      yamlCfg.mssql?.trust_server_certificate ?? true,
    ),
    enableArithAbort: true,
  },
  pool: {
    max: 10,
    min: 0,
    idleTimeoutMillis: 30_000,
  },
};
