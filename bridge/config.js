import { cliMsgDir, credentialsPath, qrPath } from "../paths.js";

function parseInteger(value, fallback, label, { min, max }) {
  const raw = value === undefined || value === "" ? fallback : Number(value);
  if (!Number.isInteger(raw) || raw < min || raw > max) {
    throw new Error(label + " must be an integer between " + min + " and " + max);
  }
  return raw;
}

function truthy(value) {
  return /^(1|true|yes|on)$/i.test(String(value || ""));
}

export function loadBridgeConfig(env = process.env) {
  const token = String(env.ZALO_PLUGIN_TOKEN || "");
  if (!token) throw new Error("ZALO_PLUGIN_TOKEN is required");
  if (Buffer.byteLength(token, "utf8") < 32) {
    throw new Error("ZALO_PLUGIN_TOKEN must contain at least 32 UTF-8 bytes");
  }
  const host = String(env.ZALO_PLUGIN_HOST || "127.0.0.1").trim();
  if (host !== "127.0.0.1") {
    throw new Error("ZALO_PLUGIN_HOST must be 127.0.0.1 (loopback-only)");
  }
  const port = parseInteger(env.ZALO_PLUGIN_PORT, 8787, "ZALO_PLUGIN_PORT", {
    min: 1,
    max: 65535,
  });
  const cliMsgRetentionDays = parseInteger(
    env.ZALO_CLIMSG_RETENTION_DAYS,
    30,
    "ZALO_CLIMSG_RETENTION_DAYS",
    { min: 0, max: 3650 },
  );
  const infoCacheTtlMs =
    parseInteger(env.ZALO_INFO_CACHE_TTL, 600, "ZALO_INFO_CACHE_TTL", {
      min: 1,
      max: 86400,
    }) * 1000;
  const infoMinIntervalMs = parseInteger(
    env.ZALO_INFO_MIN_INTERVAL_MS,
    1500,
    "ZALO_INFO_MIN_INTERVAL_MS",
    { min: 0, max: 60000 },
  );
  const requestTimeoutMs = parseInteger(
    env.ZALO_REQUEST_TIMEOUT_MS,
    55000,
    "ZALO_REQUEST_TIMEOUT_MS",
    { min: 100, max: 600000 },
  );
  return Object.freeze({
    host,
    port,
    token,
    jsonLimit: "2mb",
    credentialsPath: env.ZALO_CREDENTIALS_PATH || credentialsPath(),
    qrPath: env.ZALO_QR_PATH || qrPath(),
    cliMsgDir: env.ZALO_CLIMSG_DIR || cliMsgDir(),
    cliMsgRetentionDays,
    infoCacheTtlMs,
    infoMinIntervalMs,
    requestTimeoutMs,
    selfListen: truthy(env.ZALO_SELF_LISTEN),
    forceQr: truthy(env.ZALO_FORCE_QR),
  });
}
