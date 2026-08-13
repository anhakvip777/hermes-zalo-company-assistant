import express from "express";
import fs from "node:fs";

import { createBridgeAuth } from "./auth.js";
import { EventBuffer } from "./event-buffer.js";
import { redactSecrets, safeError } from "./redaction.js";


function requireLogin(client, res) {
  if (!client.loggedIn || client.sessionDead) {
    res.status(503).json({
      error: "Zalo session is not logged in",
      sessionDead: Boolean(client.sessionDead),
    });
    return false;
  }
  return true;
}


function resultOf(value) {
  return { success: true, result: redactSecrets(value ?? null) };
}


function failResponse(res, error, fallbackStatus = 500) {
  const message = safeError(error);
  const lower = String(message).toLowerCase();
  let status = fallbackStatus;
  if (lower.includes("unknown zca-js api method")) status = 404;
  if (lower.includes("not available through chat")) status = 403;
  if (lower.includes("rate") || lower.includes("429")) status = 429;
  if (
    lower.includes("timed out") ||
    lower.includes("timeout") ||
    lower.includes("outcome unknown")
  ) {
    status = 504;
  }
  res.status(status).json({
    error: message,
    outcome: status === 504 ? "unknown" : "failed",
  });
}


function bodyOrEmpty(req) {
  return req.body && typeof req.body === "object" ? req.body : {};
}


function withDeadline(operation, timeoutMs) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      reject(
        new Error(
          "Zalo provider call timed out after " +
            timeoutMs +
            "ms; outcome unknown",
        ),
      );
    }, timeoutMs);
  });
  return Promise.race([Promise.resolve().then(operation), deadline]).finally(() => {
    clearTimeout(timer);
  });
}


export function createBridgeApp({
  client,
  config,
  eventBuffer = new EventBuffer(),
  catalog,
  onShutdown,
} = {}) {
  if (!client) throw new Error("client is required");
  if (!config || !config.token) throw new Error("bridge config with token is required");
  if (!catalog) throw new Error("method catalog is required");

  const app = express();
  app.locals.client = client;
  app.locals.eventBuffer = eventBuffer;
  app.locals.catalog = catalog;
  app.use(createBridgeAuth(config.token));
  app.use(express.json({ limit: config.jsonLimit || "2mb" }));

  const requestTimeoutMs =
    Number.isFinite(config.requestTimeoutMs) && config.requestTimeoutMs > 0
      ? config.requestTimeoutMs
      : 55000;
  const invoke = (operation) => withDeadline(operation, requestTimeoutMs);
  const shutdownRuntime =
    typeof onShutdown === "function"
      ? onShutdown
      : () => client.shutdown?.();

  const eventNames = [
    "message",
    "status",
    "session_dead",
    "reaction",
    "undo",
    "friend_event",
    "group_event",
  ];
  for (const eventName of eventNames) {
    client.on?.(eventName, (payload) => {
      eventBuffer.publish(eventName, redactSecrets(payload));
    });
  }

  app.get("/health", (_req, res) => {
    const qrState =
      typeof client.qrState === "object" ? client.qrState?.status : client.qrState;
    res.json({
      ok: true,
      loggedIn: Boolean(client.loggedIn),
      sessionDead: Boolean(client.sessionDead),
      sessionDeadReason: redactSecrets(client.sessionDeadReason || null),
      ownId: client.ownId ? String(client.ownId) : null,
      qr: qrState || (client.loggedIn ? "authenticated" : "missing"),
      sseClients: eventBuffer.clientCount,
    });
  });

  app.get("/policy", (_req, res) => {
    res.json({
      mode: "all_operational_methods",
      totalActions: catalog.list().length,
      allowedActionCount: catalog.list().length,
      sensitiveMethodsHidden: 3,
      blockedMethods: ["getCookie", "getContext", "getQR"],
    });
  });

  app.get("/events", (req, res) => {
    eventBuffer.attach(req, res);
  });

  app.get("/qr", (_req, res) => {
    const state = client.qrState || {};
    res.json({
      status: redactSecrets(state.status || (client.loggedIn ? "authenticated" : "idle")),
      expiresAt: redactSecrets(state.expiresAt || null),
    });
  });

  app.get("/qr.png", (_req, res) => {
    const image = client.qrState?.image;
    if (!image) {
      res.status(404).json({ error: "QR image is not available" });
      return;
    }
    const raw = String(image).replace(/^data:image\/png;base64,/, "");
    res.type("png").send(Buffer.from(raw, "base64"));
  });

  app.post("/relogin", async (req, res) => {
    try {
      const result = await invoke(() => client.relogin?.(bodyOrEmpty(req)));
      res.json(resultOf(result));
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/shutdown", async (_req, res) => {
    try {
      res.set("connection", "close");
      const result = await invoke(() => shutdownRuntime());
      res.json(resultOf(result || { stopped: true }));
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/send", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId || typeof body.text !== "string") {
      res.status(400).json({ error: "threadId and text are required" });
      return;
    }
    try {
      const result = await invoke(() =>
        client.sendText(
          String(body.threadId),
          body.threadType === "group" ? "group" : "user",
          body.text,
          body.mentions,
          body.quote,
        ),
      );
      res.json(resultOf(result));
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/send-attachment", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    const paths = Array.isArray(body.paths)
      ? body.paths
      : body.path
        ? [body.path]
        : [];
    if (!body.threadId || paths.length === 0) {
      res.status(400).json({ error: "threadId and path or paths are required" });
      return;
    }
    const missingPath = paths.find((filePath) => !fs.existsSync(filePath));
    if (missingPath) {
      res.status(400).json({ error: "file not found: " + missingPath });
      return;
    }
    try {
      const result = await invoke(() =>
        client.sendAttachment(
          String(body.threadId),
          body.threadType === "group" ? "group" : "user",
          paths,
          body.caption || "",
        ),
      );
      res.json(resultOf(result));
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/send-sticker", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId || !body.sticker) {
      res.status(400).json({ error: "threadId and sticker are required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.sendSticker(
              String(body.threadId),
              body.threadType === "group" ? "group" : "user",
              body.sticker,
            ),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/send-voice", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId || (!body.voiceUrl && !body.path)) {
      res.status(400).json({
        error: "threadId and voiceUrl or path are required",
      });
      return;
    }
    if (body.path && !fs.existsSync(body.path)) {
      res.status(400).json({ error: "file not found: " + body.path });
      return;
    }
    try {
      const threadId = String(body.threadId);
      const threadType = body.threadType === "group" ? "group" : "user";
      res.json(
        resultOf(
          await invoke(() =>
            body.path
              ? client.sendVoiceLocal(threadId, threadType, body.path)
              : client.sendVoice(threadId, threadType, body.voiceUrl),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/typing", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId) {
      res.status(400).json({ error: "threadId is required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.sendTyping(
              String(body.threadId),
              body.threadType === "group" ? "group" : "user",
            ),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/send-card", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId || !body.userId) {
      res.status(400).json({ error: "threadId and userId are required" });
      return;
    }
    try {
      const result = await invoke(() =>
        client.sendCard(
          String(body.threadId),
          body.threadType === "group" ? "group" : "user",
          String(body.userId),
          body.phoneNumber,
        ),
      );
      res.json(resultOf(result));
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/friend/request", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.userId) {
      res.status(400).json({ error: "userId is required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.sendFriendRequest(String(body.userId), body.msg),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/friend/accept", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.userId) {
      res.status(400).json({ error: "userId is required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() => client.acceptFriendRequest(String(body.userId))),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/friend/reject", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.userId) {
      res.status(400).json({ error: "userId is required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() => client.rejectFriendRequest(String(body.userId))),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.get("/chat-info", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const threadId = req.query.threadId || req.query.userId || req.query.id;
    if (!threadId) {
      res.status(400).json({ error: "threadId is required" });
      return;
    }
    try {
      const operation =
        req.query.threadType === "group"
          ? () => client.getGroupInfo(String(threadId))
          : () => client.getUserInfo(String(threadId));
      res.json(resultOf(await invoke(operation)));
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.get("/group-members", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const groupId = String(req.query.groupId || "").trim();
    if (!groupId) {
      res.status(400).json({ error: "groupId is required" });
      return;
    }
    try {
      res.json(
        resultOf(await invoke(() => client.getGroupMembers(groupId))),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.get("/friends", async (_req, res) => {
    if (!requireLogin(client, res)) return;
    try {
      res.json(resultOf(await invoke(() => client.getAllFriends())));
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.get("/groups", async (_req, res) => {
    if (!requireLogin(client, res)) return;
    try {
      res.json(resultOf(await invoke(() => client.getAllGroups())));
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.get("/contacts", async (_req, res) => {
    if (!requireLogin(client, res)) return;
    try {
      res.json(resultOf(await invoke(() => client.listContacts())));
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.get("/find-user", async (req, res) => {
    if (!requireLogin(client, res)) return;
    if (!req.query.phone) {
      res.status(400).json({ error: "phone is required" });
      return;
    }
    try {
      res.json(
        resultOf(await invoke(() => client.findUser(String(req.query.phone)))),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.get("/stickers", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const keyword = req.query.keyword || req.query.q;
    if (!keyword) {
      res.status(400).json({ error: "keyword is required" });
      return;
    }
    const parsedLimit = Number.parseInt(String(req.query.limit || "5"), 10);
    const limit = Number.isInteger(parsedLimit) && parsedLimit > 0 ? parsedLimit : 5;
    try {
      res.json(
        resultOf(
          await invoke(() => client.findStickers(String(keyword), limit)),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/group/create", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!Array.isArray(body.members) || body.members.length === 0) {
      res.status(400).json({ error: "members must be a non-empty array" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() => client.createGroup(body.name, body.members)),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/group/add", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.groupId || !Array.isArray(body.members) || body.members.length === 0) {
      res.status(400).json({
        error: "groupId and a non-empty members array are required",
      });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.addUserToGroup(String(body.groupId), body.members),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/group/remove", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.groupId || !Array.isArray(body.members) || body.members.length === 0) {
      res.status(400).json({
        error: "groupId and a non-empty members array are required",
      });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.removeUserFromGroup(String(body.groupId), body.members),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/group/rename", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.groupId || !body.name) {
      res.status(400).json({ error: "groupId and name are required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.changeGroupName(String(body.groupId), String(body.name)),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/group/deputy", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.groupId || !Array.isArray(body.members) || body.members.length === 0) {
      res.status(400).json({
        error: "groupId and a non-empty members array are required",
      });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.addGroupDeputy(String(body.groupId), body.members),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/group/leave", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.groupId) {
      res.status(400).json({ error: "groupId is required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.leaveGroup(String(body.groupId), Boolean(body.silent)),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/poll/create", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (
      !body.groupId ||
      !body.question ||
      !Array.isArray(body.options) ||
      body.options.length < 2
    ) {
      res.status(400).json({
        error: "groupId, question and at least two options are required",
      });
      return;
    }
    const { groupId, question, options, ...extra } = body;
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.createPoll(String(groupId), String(question), options, extra),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.post("/react", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId || !body.msgId) {
      res.status(400).json({ error: "threadId and msgId are required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.react(
              String(body.threadId),
              body.threadType === "group" ? "group" : "user",
              String(body.msgId),
              body.cliMsgId ? String(body.cliMsgId) : undefined,
              body.icon || "HEART",
            ),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });
  app.post("/undo", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const body = bodyOrEmpty(req);
    if (!body.threadId || !body.msgId) {
      res.status(400).json({ error: "threadId and msgId are required" });
      return;
    }
    try {
      res.json(
        resultOf(
          await invoke(() =>
            client.undo(
              String(body.threadId),
              body.threadType === "group" ? "group" : "user",
              String(body.msgId),
              body.cliMsgId ? String(body.cliMsgId) : undefined,
            ),
          ),
        ),
      );
    } catch (error) {
      failResponse(res, error);
    }
  });

  app.get("/api/methods", (req, res) => {
    res.json({ version: catalog.version, methods: catalog.list(req.query.query) });
  });
  app.get("/api/methods/:method", (req, res) => {
    try {
      res.json({ version: catalog.version, method: catalog.describe(req.params.method) });
    } catch (error) {
      failResponse(res, error, 404);
    }
  });

  app.post("/api/:method", async (req, res) => {
    if (!requireLogin(client, res)) return;
    const method = String(req.params.method || "");
    if (catalog.isSensitive(method)) {
      res.status(403).json({ error: "method is not available through chat" });
      return;
    }
    if (!catalog.has(method)) {
      res.status(404).json({ error: "unknown zca-js API method: " + method });
      return;
    }
    let args;
    try {
      args = catalog.toArgs(method, bodyOrEmpty(req));
    } catch (error) {
      failResponse(res, error, 400);
      return;
    }
    try {
      const result = await invoke(() => client.callRaw(method, args));
      res.json(resultOf(result));
    } catch (error) {
      failResponse(res, error);
    }
  });

  return app;
}
