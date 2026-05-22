import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";

const ROOT = path.resolve(process.cwd(), "..");

interface YamlSettings {
  storage?: { db_path?: string; shared_root?: string };
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

export const DB_PATH = path.resolve(
  process.env.CAPTURE_DB ||
    yamlCfg.storage?.db_path ||
    path.join(ROOT, "logs", "captures.db"),
);

export const SHARE_ROOT = path.resolve(
  process.env.SHARE_ROOT || yamlCfg.storage?.shared_root || ".",
);
