#!/usr/bin/env node
// Migrate the legacy 1.0.9 environment/config into the company-assistant
// gateway.platforms.zalo.extra block.  Secrets are deliberately never written
// to YAML; keep ZALO_PLUGIN_TOKEN in the service EnvironmentFile.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const KEY_MAP = Object.freeze({
  ZALO_PLUGIN_URL: "bridge_url",
  ZALO_ALLOWED_USERS: "allowed_users",
  ZALO_ADMIN_USERS: "admin_users",
  ZALO_ALLOWED_GROUPS: "allowed_groups",
  ZALO_GROUP_MODE: "group_mode",
  ZALO_HISTORY_CONTEXT_MESSAGES: "history_context_messages",
  ZALO_MEDIA_MAX_BYTES: "media_max_bytes",
  ZALO_HISTORY_RETENTION: "history_retention",
});

function parseEnvFile(filePath) {
  const result = {};
  if (!filePath || !fs.existsSync(filePath)) return result;
  for (const line of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const match = /^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (!match) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    result[match[1]] = value;
  }
  return result;
}

function yamlScalar(value, key) {
  if (["allowed_users", "admin_users", "allowed_groups"].includes(key)) {
    const values = String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
    return JSON.stringify(values);
  }
  if (/^(history_context_messages|media_max_bytes)$/.test(key) && /^\d+$/.test(String(value))) {
    return String(value);
  }
  return JSON.stringify(String(value));
}

function blockEnd(lines, start, indent) {
  for (let index = start + 1; index < lines.length; index += 1) {
    if (!lines[index].trim()) continue;
    const currentIndent = (lines[index].match(/^\s*/) || [""])[0].length;
    if (currentIndent <= indent) return index;
  }
  return lines.length;
}

function lineIndent(line) {
  return (line.match(/^\s*/) || [""])[0].length;
}

function findChild(lines, parentIndex, parentIndent, name) {
  const end = blockEnd(lines, parentIndex, parentIndent);
  const expression = new RegExp(`^\\s{${parentIndent + 2}}${name}\\s*:`);
  for (let index = parentIndex + 1; index < end; index += 1) {
    if (expression.test(lines[index])) return index;
  }
  return -1;
}

function locateZaloExtra(lines) {
  const gatewayIndex = lines.findIndex((line) => /^gateway\s*:\s*$/.test(line));
  if (gatewayIndex < 0 || lineIndent(lines[gatewayIndex]) !== 0) return null;
  const platformsIndex = findChild(lines, gatewayIndex, 0, "platforms");
  if (platformsIndex < 0) return null;
  const platformsIndent = lineIndent(lines[platformsIndex]);
  const zaloIndex = findChild(lines, platformsIndex, platformsIndent, "zalo");
  if (zaloIndex < 0) return null;
  const zaloIndent = lineIndent(lines[zaloIndex]);
  const extraIndex = findChild(lines, zaloIndex, zaloIndent, "extra");
  if (extraIndex >= 0) return { extraIndex };
  return {
    insertAt: blockEnd(lines, zaloIndex, zaloIndent),
    extraIndent: zaloIndent + 2,
  };
}

function upsertExtra(text, values) {
  const lines = text.split(/\r?\n/);
  let extraIndex = -1;
  const located = locateZaloExtra(lines);
  if (located?.extraIndex !== undefined) extraIndex = located.extraIndex;
  if (extraIndex < 0) {
    if (located?.insertAt !== undefined) {
      lines.splice(located.insertAt, 0, " ".repeat(located.extraIndent) + "extra:");
      extraIndex = located.insertAt;
    } else {
      if (lines.length && lines.at(-1) !== "") lines.push("");
      lines.push("gateway:", "  platforms:", "    zalo:", "      extra:");
      extraIndex = lines.length - 1;
    }
  }

  const extraIndent = (lines[extraIndex].match(/^\s*/) || [""])[0].length;
  const childIndent = " ".repeat(extraIndent + 2);
  const end = blockEnd(lines, extraIndex, extraIndent);
  const existing = lines.slice(extraIndex + 1, end);
  const kept = existing.filter((line) => {
    const match = new RegExp(`^\\s+(${Object.values(KEY_MAP).join("|")}):`).exec(line);
    return !match || !Object.hasOwn(values, match[1]);
  });
  const rendered = Object.entries(values).map(([key, value]) => `${childIndent}${key}: ${yamlScalar(value, key)}`);
  lines.splice(extraIndex + 1, end - extraIndex - 1, ...kept, ...rendered);
  return lines.join("\n");
}

export function migrateConfig({ configPath, env = process.env, envFile = "" }) {
  const file = path.resolve(String(configPath));
  const source = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  const mergedEnv = { ...parseEnvFile(envFile), ...env };
  const values = {};
  for (const [environmentName, targetName] of Object.entries(KEY_MAP)) {
    if (mergedEnv[environmentName] !== undefined && mergedEnv[environmentName] !== "") {
      values[targetName] = mergedEnv[environmentName];
    }
  }
  // The company assistant has one fixed group behavior: persist every
  // allowlisted-group message, but dispatch Hermes only on an allowed mention.
  // Legacy `all`/`off` values must not survive the migration.
  values.group_mode = "mention";
  // Conservative defaults required by the new fail-closed adapter are only
  // written when explicitly supplied; never invent an allow-all list.
  const migrated = upsertExtra(source, values);
  if (migrated !== source) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temporary = file + ".tmp";
    fs.writeFileSync(temporary, migrated, { encoding: "utf8", mode: 0o600 });
    fs.renameSync(temporary, file);
  }
  return { configPath: file, changed: migrated !== source, migratedKeys: Object.keys(values) };
}

function main() {
  const args = process.argv.slice(2);
  const configFlag = args.indexOf("--config");
  const envFlag = args.indexOf("--env-file");
  const configPath = configFlag >= 0 ? args[configFlag + 1] : process.env.HERMES_CONFIG;
  if (!configPath) {
    console.error("Usage: migrate-v1.0.9-config.mjs --config <config.yaml> [--env-file <file>]");
    process.exitCode = 2;
    return;
  }
  const result = migrateConfig({
    configPath,
    envFile: envFlag >= 0 ? args[envFlag + 1] : "",
  });
  console.log(JSON.stringify(result, null, 2));
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) main();
