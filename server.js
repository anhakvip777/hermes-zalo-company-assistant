// Node bridge entrypoint for the Hermes company assistant.
//
// The bridge is deliberately a small process boundary: it owns the zca-js
// session, exposes the complete operational API through an authenticated
// loopback HTTP/SSE surface, and never decides Hermes roles.

import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createBridgeApp } from "./bridge/app.js";
import { loadBridgeConfig } from "./bridge/config.js";
import { EventBuffer } from "./bridge/event-buffer.js";
import { MethodCatalog } from "./bridge/method-catalog.js";
import { redactText, safeError } from "./bridge/redaction.js";
import { loadRuntimeEnv } from "./paths.js";
import { ZaloClient } from "./zaloClient.js";


export function createRuntime(env = process.env) {
  const config = loadBridgeConfig(env === process.env ? loadRuntimeEnv(env) : env);
  const client = new ZaloClient({
    credentialsPath: config.credentialsPath,
    qrPath: config.qrPath,
    selfListen: config.selfListen,
    cliMsgDir: config.cliMsgDir,
    cliMsgRetentionDays: config.cliMsgRetentionDays,
    infoCacheTtlMs: config.infoCacheTtlMs,
    infoMinIntervalMs: config.infoMinIntervalMs,
  });
  const eventBuffer = new EventBuffer({ capacity: 200 });
  const catalog = MethodCatalog.fromInstalledPackage({ liveApi: client.api });
  let runtime;
  const app = createBridgeApp({
    client,
    config,
    eventBuffer,
    catalog,
    onShutdown: async () => {
      await stopRuntime(runtime, "HTTP /shutdown", { waitForClose: false });
      return { stopped: true };
    },
  });
  const server = http.createServer(app);
  runtime = { app, catalog, client, config, eventBuffer, server };
  return runtime;
}


export async function startRuntime(runtime = createRuntime()) {
  const { catalog, client, config, server } = runtime;
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.port, config.host, resolve);
  });
  console.log(
    redactText("[bridge] listening on http://" + config.host + ":" + config.port),
  );
  try {
    const result = await client.login({ forceQR: config.forceQr });
    catalog.liveApi = client.api;
    console.log(redactText("[bridge] login complete via " + result.method));
  } catch (error) {
    console.error("[bridge] login failed:", safeError(error));
    console.error("[bridge] server remains available for authenticated admin QR flow");
  }
  return runtime;
}


export async function stopRuntime(
  runtime,
  reason = "shutdown",
  { waitForClose = true } = {},
) {
  if (!runtime) return;
  console.log(redactText("[bridge] graceful shutdown (" + reason + ")"));
  runtime.eventBuffer.closeAll();
  try {
    await runtime.client.shutdown();
  } catch {
    // Best effort during process teardown.
  }
  if (!runtime.server.listening) return;
  if (!waitForClose) {
    runtime.server.close();
    return;
  }
  await new Promise((resolve) => runtime.server.close(() => resolve()));
}


const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  let runtime;
  try {
    runtime = createRuntime();
    await startRuntime(runtime);
    const shutdown = async (signal) => {
      await stopRuntime(runtime, signal);
      process.exit(0);
    };
    process.once("SIGTERM", () => void shutdown("SIGTERM"));
    process.once("SIGINT", () => void shutdown("SIGINT"));
  } catch (error) {
    console.error("[bridge] startup failed:", safeError(error));
    process.exitCode = 1;
  }
}
