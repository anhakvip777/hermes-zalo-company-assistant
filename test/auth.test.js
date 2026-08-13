import assert from "node:assert/strict";
import express from "express";
import test from "node:test";

import { createBridgeAuth } from "../bridge/auth.js";
import { authHeaders, withServer } from "./helpers/fake-zalo-client.js";


const TOKEN = "x".repeat(32);


test("auth accepts Bearer token and rejects missing, invalid, and query tokens", async () => {
  const app = express();
  app.use(createBridgeAuth(TOKEN));
  app.get("/health", (_req, res) => res.json({ ok: true }));

  await withServer(app, async (baseUrl) => {
    assert.equal((await fetch(baseUrl + "/health")).status, 401);
    assert.equal(
      (
        await fetch(baseUrl + "/health", {
          headers: authHeaders("y".repeat(32)),
        })
      ).status,
      401,
    );
    assert.equal(
      (await fetch(baseUrl + "/health?token=" + TOKEN)).status,
      401,
    );
    const valid = await fetch(baseUrl + "/health", {
      headers: authHeaders(TOKEN),
    });
    assert.equal(valid.status, 200);
    assert.deepEqual(await valid.json(), { ok: true });
  });
});


test("legacy x-bridge-token remains authenticated for the installed adapter", async () => {
  const app = express();
  app.use(createBridgeAuth(TOKEN));
  app.get("/health", (_req, res) => res.json({ ok: true }));

  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/health", {
      headers: { "x-bridge-token": TOKEN },
    });
    assert.equal(response.status, 200);
  });
});
