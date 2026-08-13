// paths.js — central resolution of where the bridge stores its data.
//
// When installed globally (npm i -g), the package directory is read-only and
// gets wiped on update, so credentials/QR/cache MUST live in the user's home,
// not next to the code. Resolution order:
//   1) explicit env (ZALO_DATA_DIR, or per-file ZALO_CREDENTIALS_PATH/ZALO_QR_PATH)
//   2) ~/.hermes-zalo/   (default for global/CLI installs)
//
// A local dev checkout can opt back into ./data by setting
// ZALO_DATA_DIR=./data (or running with that env), keeping old behaviour.

import os from "node:os";
import path from "node:path";
import fs from "node:fs";

export function dataDir() {
  const fromEnv = process.env.ZALO_DATA_DIR;
  const dir = fromEnv && fromEnv.trim()
    ? path.resolve(fromEnv.trim())
    : path.join(os.homedir(), ".hermes-zalo");
  fs.mkdirSync(dir, { recursive: true });
  try {
    fs.chmodSync(dir, 0o700);
  } catch {
    // Best effort on Windows and filesystems without POSIX modes.
  }
  return dir;
}

export function credentialsPath() {
  return process.env.ZALO_CREDENTIALS_PATH || path.join(dataDir(), "credentials.json");
}

export function qrPath() {
  return process.env.ZALO_QR_PATH || path.join(dataDir(), "qr.png");
}

export function cliMsgDir() {
  return process.env.ZALO_CLIMSG_DIR || path.join(dataDir(), "climsgids");
}

export function logDir() {
  return process.env.ZALO_LOG_DIR || dataDir();
}

export function historyDir() {
  const dir = process.env.ZALO_HISTORY_DIR || path.join(dataDir(), "history");
  fs.mkdirSync(dir, { recursive: true });
  try {
    fs.chmodSync(dir, 0o700);
  } catch {
    // Best effort on Windows.
  }
  return dir;
}

export function databasePath() {
  return process.env.ZALO_DB_PATH || path.join(historyDir(), "conversations.sqlite3");
}

export function mediaDir() {
  const dir = process.env.ZALO_MEDIA_DIR || path.join(historyDir(), "media");
  fs.mkdirSync(dir, { recursive: true });
  try {
    fs.chmodSync(dir, 0o700);
  } catch {
    // Best effort on Windows.
  }
  return dir;
}

export function exportsDir() {
  const dir = process.env.ZALO_EXPORTS_DIR || path.join(dataDir(), "exports");
  fs.mkdirSync(dir, { recursive: true });
  try {
    fs.chmodSync(dir, 0o700);
  } catch {
    // Best effort on Windows.
  }
  return dir;
}

export function runtimeEnvPath() {
  return process.env.ZALO_RUNTIME_ENV_FILE || path.join(dataDir(), "company.env");
}

/** Read the private runtime env file without overwriting explicit process env. */
export function loadRuntimeEnv(base = process.env) {
  const merged = { ...base };
  const file = base.ZALO_RUNTIME_ENV_FILE || runtimeEnvPath();
  try {
    const text = fs.readFileSync(file, "utf8");
    for (const line of text.split(/\r?\n/)) {
      const match = /^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
      if (!match || Object.hasOwn(base, match[1])) continue;
      let value = match[2];
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      merged[match[1]] = value;
    }
  } catch {
    // The installer creates this file. Direct development runs may use only
    // explicit process environment variables.
  }
  return merged;
}
