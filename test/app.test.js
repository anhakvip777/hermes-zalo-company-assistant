import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import { createBridgeApp } from "../bridge/app.js";
import { EventBuffer } from "../bridge/event-buffer.js";
import { MethodCatalog } from "../bridge/method-catalog.js";
import { redactSecrets, redactText, safeError } from "../bridge/redaction.js";
import { createRuntime, startRuntime } from "../server.js";
import { ZaloClient } from "../zaloClient.js";
import {
  FakeZaloClient,
  authHeaders,
  withServer,
} from "./helpers/fake-zalo-client.js";


const TOKEN = "x".repeat(32);


function makeApp({ client = new FakeZaloClient(), onShutdown, requestTimeoutMs } = {}) {
  const catalog = MethodCatalog.fromInstalledPackage({
    liveApi: client.api,
  });
  const eventBuffer = new EventBuffer({ capacity: 10 });
  const app = createBridgeApp({
    client,
    eventBuffer,
    catalog,
    config: {
      token: TOKEN,
      host: "127.0.0.1",
      port: 8787,
      jsonLimit: "2mb",
      requestTimeoutMs,
    },
    onShutdown,
  });
  return { app, client, eventBuffer };
}


test("auth runs before JSON parsing so malformed unauthenticated JSON is 401", async () => {
  const { app } = makeApp();
  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/send", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{",
    });
    assert.equal(response.status, 401);
  });
});


test("every bridge route, including health and method catalog, requires auth", async () => {
  const { app } = makeApp();
  await withServer(app, async (baseUrl) => {
    for (const path of ["/health", "/policy", "/api/methods", "/qr", "/events"]) {
      const response = await fetch(baseUrl + path, {
        signal: AbortSignal.timeout(1_000),
      });
      assert.equal(response.status, 401, path);
    }
  });
});


test("health and catalog return safe operational metadata", async () => {
  const { app } = makeApp();
  await withServer(app, async (baseUrl) => {
    const health = await fetch(baseUrl + "/health", {
      headers: authHeaders(TOKEN),
    });
    assert.equal(health.status, 200);
    assert.deepEqual(await health.json(), {
      ok: true,
      loggedIn: true,
      sessionDead: false,
      sessionDeadReason: null,
      ownId: "bot-id",
      qr: "authenticated",
      sseClients: 0,
    });

    const catalog = await fetch(baseUrl + "/api/methods?query=poll", {
      headers: authHeaders(TOKEN),
    });
    const body = await catalog.json();
    assert.equal(body.version, "2.1.2");
    assert.ok(body.methods.some((entry) => entry.name === "createPoll"));
  });
});


test("generic call supports named params and recursively redacts results", async () => {
  const { app, client } = makeApp();
  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/api/sendMessage", {
      method: "POST",
      headers: {
        ...authHeaders(TOKEN),
        "content-type": "application/json",
      },
      body: JSON.stringify({
        params: {
          message: "xin chào",
          threadId: "u-1",
          type: "user",
        },
      }),
    });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.success, true);
    assert.equal(body.result.token, "[REDACTED]");
    assert.equal(client.calls[0].method, "sendMessage");
    assert.deepEqual(client.calls[0].args, ["xin chào", "u-1", "user"]);
  });
});


test("credential methods are denied even for an authenticated caller", async () => {
  const { app, client } = makeApp();
  await withServer(app, async (baseUrl) => {
    for (const method of ["getCookie", "getContext"]) {
      const response = await fetch(baseUrl + "/api/" + method, {
        method: "POST",
        headers: {
          ...authHeaders(TOKEN),
          "content-type": "application/json",
        },
        body: "{}",
      });
      assert.equal(response.status, 403);
    }
    assert.equal(client.calls.length, 0);
  });
});


test("credential method variants and unclassified live methods fail closed", async () => {
  const client = new FakeZaloClient();
  client.api.GETCOOKIE = () => "secret";
  client.api.futureUnknownMethod = () => "future";
  const { app } = makeApp({ client });
  await withServer(app, async (baseUrl) => {
    for (const [method, expectedStatus] of [
      ["GETCOOKIE", 403],
      ["GetContext", 403],
      ["getqr", 403],
      ["futureUnknownMethod", 404],
    ]) {
      const response = await fetch(baseUrl + "/api/" + method, {
        method: "POST",
        headers: {
          ...authHeaders(TOKEN),
          "content-type": "application/json",
        },
        body: JSON.stringify({ args: [] }),
      });
      assert.equal(response.status, expectedStatus, method);
    }
    assert.equal(client.calls.length, 0);
  });
});


test("unknown methods are not invoked and return a clear 404", async () => {
  const { app } = makeApp();
  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/api/notARealMethod", {
      method: "POST",
      headers: {
        ...authHeaders(TOKEN),
        "content-type": "application/json",
      },
      body: JSON.stringify({ args: [] }),
    });
    assert.equal(response.status, 404);
    assert.match((await response.json()).error, /unknown/i);
  });
});


test("all convenience routes from the 1.0.9 baseline remain callable", async () => {
  const { app, client } = makeApp();
  const cases = [
    ["/send-card", { threadId: "u-1", userId: "u-2" }, "sendCard", ["u-1", "user", "u-2", undefined]],
    ["/friend/request", { userId: "u-2", msg: "xin chào" }, "sendFriendRequest", ["u-2", "xin chào"]],
    ["/friend/accept", { userId: "u-2" }, "acceptFriendRequest", ["u-2"]],
    ["/friend/reject", { userId: "u-2" }, "rejectFriendRequest", ["u-2"]],
    ["/group/create", { name: "Công ty", members: ["u-1", "u-2"] }, "createGroup", ["Công ty", ["u-1", "u-2"]]],
    ["/group/add", { groupId: "g-1", members: ["u-2"] }, "addUserToGroup", ["g-1", ["u-2"]]],
    ["/group/remove", { groupId: "g-1", members: ["u-2"] }, "removeUserFromGroup", ["g-1", ["u-2"]]],
    ["/group/rename", { groupId: "g-1", name: "Tên mới" }, "changeGroupName", ["g-1", "Tên mới"]],
    ["/group/deputy", { groupId: "g-1", members: ["u-2"] }, "addGroupDeputy", ["g-1", ["u-2"]]],
    ["/group/leave", { groupId: "g-1", silent: true }, "leaveGroup", ["g-1", true]],
    ["/poll/create", { groupId: "g-1", question: "Ăn gì?", options: ["A", "B"], isAnonymous: true }, "createPoll", ["g-1", "Ăn gì?", ["A", "B"], { isAnonymous: true }]],
  ];

  await withServer(app, async (baseUrl) => {
    for (const [path, body, method, args] of cases) {
      const response = await fetch(baseUrl + path, {
        method: "POST",
        headers: {
          ...authHeaders(TOKEN),
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
      });
      assert.equal(response.status, 200, path);
      assert.equal((await response.json()).success, true, path);
      assert.deepEqual(client.calls.at(-1), { method, args }, path);
    }
  });
});


test("shutdown delegates to the app-factory runtime callback", async () => {
  let shutdownCalls = 0;
  const { app, client } = makeApp({
    onShutdown: async () => {
      shutdownCalls += 1;
      return { stopped: true };
    },
  });

  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/shutdown", {
      method: "POST",
      headers: authHeaders(TOKEN),
    });
    assert.equal(response.status, 200);
    assert.equal(shutdownCalls, 1);
    assert.equal(client.loggedIn, true, "the runtime callback owns client/server shutdown");
  });
});


test("runtime wires HTTP shutdown to close its client and server", async () => {
  const runtime = createRuntime({ ZALO_PLUGIN_TOKEN: TOKEN });
  runtime.server.listen(0, "127.0.0.1");
  await new Promise((resolve) => runtime.server.once("listening", resolve));
  const closed = new Promise((resolve) => runtime.server.once("close", resolve));
  const address = runtime.server.address();

  try {
    const response = await fetch(
      "http://127.0.0.1:" + address.port + "/shutdown",
      { method: "POST", headers: authHeaders(TOKEN) },
    );
    assert.equal(response.status, 200);
    await Promise.race([
      closed,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("runtime server did not close")), 200),
      ),
    ]);
    assert.equal(runtime.client.loggedIn, false);
    assert.equal(runtime.server.listening, false);
  } finally {
    if (runtime.server.listening) {
      await new Promise((resolve) => runtime.server.close(resolve));
    }
  }
});


test("provider calls exceeding the bridge deadline return unknown without retry", async () => {
  const client = new FakeZaloClient();
  let attempts = 0;
  client.api.keepAlive = () => {
    attempts += 1;
    return new Promise(() => {});
  };
  const { app } = makeApp({ client, requestTimeoutMs: 15 });

  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/api/keepAlive", {
      method: "POST",
      headers: {
        ...authHeaders(TOKEN),
        "content-type": "application/json",
      },
      body: JSON.stringify({ args: [] }),
    });
    assert.equal(response.status, 504);
    const body = await response.json();
    assert.equal(body.outcome, "unknown");
    assert.match(body.error, /timed out|outcome unknown/i);
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(attempts, 1);
  });
});


test("ZaloClient getGroupMembers reads live memVerList and enriches profiles", async () => {
  const client = new ZaloClient({
    credentialsPath: "unused-credentials.json",
    qrPath: "unused-qr.png",
  });
  let requestedTokens = null;
  client.api = {
    getGroupInfo: async (groupId) => {
      assert.equal(groupId, "g-1");
      return {
        gridInfoMap: {
          "g-1": {
            currentMems: [],
            memberIds: [],
            memVerList: ["679_0", "680_0"],
          },
        },
      };
    },
    getGroupMembersInfo: async (tokens) => {
      requestedTokens = tokens;
      return {
        profiles: {
          679: {
            id: "679",
            displayName: "Lan",
            zaloName: "Lan Zalo",
            avatar: "https://example.invalid/lan.png",
            accountStatus: 0,
            type: 0,
            lastUpdateTime: 0,
            globalId: "global-679",
          },
        },
        unchangeds_profile: [],
      };
    },
  };

  const members = await client.getGroupMembers("g-1");

  assert.deepEqual(requestedTokens, ["679_0", "680_0"]);
  assert.deepEqual(members, [
    { id: "679", name: "Lan" },
    { id: "680", name: "680" },
  ]);
});


test("ZaloClient getGroupMembers keeps currentMems and memberIds when enrichment fails", async () => {
  const cases = [
    {
      group: { currentMems: [{ id: "u-current", dName: "Current Name" }] },
      expectedTokens: ["u-current"],
      expectedMembers: [{ id: "u-current", name: "Current Name" }],
    },
    {
      group: { currentMems: [], memberIds: ["u-id"] },
      expectedTokens: ["u-id"],
      expectedMembers: [{ id: "u-id", name: "u-id" }],
    },
  ];

  for (const { group, expectedTokens, expectedMembers } of cases) {
    const client = new ZaloClient({
      credentialsPath: "unused-credentials.json",
      qrPath: "unused-qr.png",
    });
    let requestedTokens = null;
    client.api = {
      getGroupInfo: async () => ({ gridInfoMap: { "g-1": group } }),
      getGroupMembersInfo: async (tokens) => {
        requestedTokens = tokens;
        throw new Error("profile enrichment unavailable");
      },
    };

    const members = await client.getGroupMembers("g-1");

    assert.deepEqual(requestedTokens, expectedTokens);
    assert.deepEqual(members, expectedMembers);
  }
});


test("ZaloClient getGroupMembers falls back to user profiles for member names", async () => {
  const client = new ZaloClient({
    credentialsPath: "unused-credentials.json",
    qrPath: "unused-qr.png",
  });
  let groupProfileCalls = 0;
  let userProfileCalls = 0;
  client.api = {
    getGroupInfo: async () => ({
      gridInfoMap: {
        "g-1": { currentMems: [], memberIds: ["679_0", "680_0"] },
      },
    }),
    getGroupMembersInfo: async () => {
      groupProfileCalls += 1;
      throw new Error("group profile endpoint unavailable");
    },
    getUserInfo: async (tokens) => {
      userProfileCalls += 1;
      assert.deepEqual(tokens, ["679_0", "680_0"]);
      return {
        changed_profiles: {
          "679_0": { id: "679", displayName: "Lan" },
          "680_0": { id: "680", displayName: "Minh" },
        },
      };
    },
  };

  const members = await client.getGroupMembers("g-1");

  assert.equal(groupProfileCalls, 1);
  assert.equal(userProfileCalls, 1);
  assert.deepEqual(members, [
    { id: "679", name: "Lan" },
    { id: "680", name: "Minh" },
  ]);
});


test("ZaloClient getGroupMembers merges partial member sources and enriches with versioned tokens", async () => {
  const client = new ZaloClient({
    credentialsPath: "unused-credentials.json",
    qrPath: "unused-qr.png",
  });
  let requestedTokens = null;
  client.api = {
    getGroupInfo: async () => ({
      gridInfoMap: {
        "g-1": {
          currentMems: [{ id: "u-1", dName: "Rich Current Name" }],
          memberIds: ["u-1", "u-2"],
          memVerList: ["u-1_0", "u-2_0"],
        },
      },
    }),
    getGroupMembersInfo: async (tokens) => {
      requestedTokens = tokens;
      return {
        profiles: {
          "u-2_0": { id: "u-2", displayName: "Enriched Second" },
        },
      };
    },
  };

  const members = await client.getGroupMembers("g-1");

  assert.deepEqual(requestedTokens, ["u-1_0", "u-2_0"]);
  assert.deepEqual(members, [
    { id: "u-1", name: "Rich Current Name" },
    { id: "u-2", name: "Enriched Second" },
  ]);
});


test("ZaloClient listContacts includes live group member counts", async () => {
  const client = new ZaloClient({
    credentialsPath: "unused-credentials.json",
    qrPath: "unused-qr.png",
  });
  client.api = {
    getAllGroups: async () => ({ gridVerMap: { "g-1": "7" } }),
    getGroupInfo: async () => ({
      gridInfoMap: {
        "g-1": {
          name: "Group AI",
          totalMember: 4,
          memVerList: ["1_0", "2_0"],
        },
      },
    }),
    getAllFriends: async () => [],
  };

  const contacts = await client.listContacts();

  assert.deepEqual(contacts.groups, [
    { id: "g-1", name: "Group AI", memberCount: 4 },
  ]);
});


test("ZaloClient listContacts counts from the fullest member source", async () => {
  const cases = [
    {
      group: {
        name: "Empty currentMems",
        currentMems: [],
        memberIds: ["u-1", "u-2"],
        memVerList: ["u-1_0", "u-2_0"],
      },
      expected: 2,
    },
    {
      group: {
        name: "Partial currentMems",
        currentMems: [{ id: "u-1", dName: "One" }],
        memberIds: ["u-1", "u-2"],
        memVerList: ["u-1_0", "u-2_0"],
      },
      expected: 2,
    },
    {
      group: {
        name: "Raw member count",
        memberCount: 7,
        currentMems: [],
        memberIds: ["u-1", "u-2"],
      },
      expected: 7,
    },
  ];

  for (const { group, expected } of cases) {
    const client = new ZaloClient({
      credentialsPath: "unused-credentials.json",
      qrPath: "unused-qr.png",
    });
    client.api = {
      getAllGroups: async () => ({ gridVerMap: { "g-1": "7" } }),
      getGroupInfo: async () => ({ gridInfoMap: { "g-1": group } }),
      getAllFriends: async () => [],
    };

    const contacts = await client.listContacts();

    assert.deepEqual(contacts.groups, [
      { id: "g-1", name: group.name, memberCount: expected },
    ]);
  }
});


test("ZaloClient listContacts preserves supported friend status fields", async () => {
  const client = new ZaloClient({
    credentialsPath: "unused-credentials.json",
    qrPath: "unused-qr.png",
  });
  client.api = {
    getAllGroups: async () => ({ gridVerMap: {} }),
    getAllFriends: async () => [
      {
        userId: "u-1",
        displayName: "Lan",
        isFr: 1,
        accountStatus: 0,
      },
    ],
  };

  const contacts = await client.listContacts();

  assert.deepEqual(contacts.friends, [
    {
      id: "u-1",
      name: "Lan",
      isFr: 1,
      accountStatus: 0,
    },
  ]);
});


test("group-members route returns the dedicated client result", async () => {
  const client = new FakeZaloClient();
  client.getGroupMembers = async (groupId) => {
    client.calls.push({ method: "getGroupMembers", args: [groupId] });
    return [{ id: "u-1", name: "Lan" }];
  };
  const { app } = makeApp({ client });

  await withServer(app, async (baseUrl) => {
    const response = await fetch(baseUrl + "/group-members?groupId=g-1", {
      headers: authHeaders(TOKEN),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      success: true,
      result: [{ id: "u-1", name: "Lan" }],
    });
    assert.deepEqual(client.calls, [
      { method: "getGroupMembers", args: ["g-1"] },
    ]);
  });
});


test("group-members route requires auth, login, and groupId", async () => {
  const client = new FakeZaloClient();
  client.getGroupMembers = async () => [];
  const { app } = makeApp({ client });

  await withServer(app, async (baseUrl) => {
    const unauthorized = await fetch(baseUrl + "/group-members?groupId=g-1");
    assert.equal(unauthorized.status, 401);

    const missingGroup = await fetch(baseUrl + "/group-members", {
      headers: authHeaders(TOKEN),
    });
    assert.equal(missingGroup.status, 400);

    client.loggedIn = false;
    const loggedOut = await fetch(baseUrl + "/group-members?groupId=g-1", {
      headers: authHeaders(TOKEN),
    });
    assert.equal(loggedOut.status, 503);
  });
});


test("text redaction covers JSON credentials and unlabeled Bearer tokens", () => {
  const jsonSecret = "json-secret-value";
  const bearerSecret = "bearer-secret-value";
  const redactedJson = redactSecrets(
    JSON.stringify({ token: jsonSecret, nested: { cookie: "cookie-secret-value" } }),
  );
  const redactedBearer = redactText("request failed with Bearer " + bearerSecret);

  assert.doesNotMatch(redactedJson, /json-secret-value|cookie-secret-value/);
  assert.doesNotMatch(redactedBearer, /bearer-secret-value/);
  assert.match(redactedJson, /REDACTED/);
  assert.match(redactedBearer, /Bearer \[REDACTED\]/i);
});


test("redaction covers composite secret keys without changing harmless text", () => {
  const rawError = safeError(new Error(
    "request failed: ACCESS_TOKEN=raw-access-value Client_Secret=raw-client-value",
  ));
  const url = redactText(
    "https://example.test/callback?refresh_token=url-refresh-value"
      + "&API_KEY=url-api-value&Api-Key=url-api-hyphen-value&mode=public",
  );
  const nested = redactSecrets({
    error: {
      detail: "callback failed: access_token=nested-access-value&state=ready",
    },
  });
  const harmless = "the refresh_token field is documented at /docs?mode=public";

  assert.equal(
    rawError,
    "request failed: ACCESS_TOKEN=[REDACTED] Client_Secret=[REDACTED]",
  );
  assert.equal(
    url,
    "https://example.test/callback?refresh_token=[REDACTED]"
      + "&API_KEY=[REDACTED]&Api-Key=[REDACTED]&mode=public",
  );
  assert.equal(
    nested.error.detail,
    "callback failed: access_token=[REDACTED]&state=ready",
  );
  assert.equal(redactText(harmless), harmless);
});


test("redaction covers camelCase and authorization assignments without overmatching", () => {
  const rawError = safeError(new Error(
    "request failed: accessToken=raw-camel authorization=Basic_raw-auth",
  ));
  const url = redactText(
    "https://example.test/callback?refreshToken=raw-refresh&mode=public",
  );
  const nested = redactSecrets({
    error: {
      detail: "callback failed: clientSecret=raw-client&state=ready",
    },
  });
  const harmless = "tokenizer=sentencepiece secretary=operations";

  assert.equal(
    rawError,
    "request failed: accessToken=[REDACTED] authorization=[REDACTED]",
  );
  assert.equal(
    url,
    "https://example.test/callback?refreshToken=[REDACTED]&mode=public",
  );
  assert.equal(
    nested.error.detail,
    "callback failed: clientSecret=[REDACTED]&state=ready",
  );
  assert.equal(redactText(harmless), harmless);
});


test("redaction hides Basic and Bearer credentials after Authorization scheme", () => {
  const basic = redactText("provider failed: Authorization: Basic dXNlcjpwYXNz");
  const bearer = redactText("provider failed: Authorization: Bearer bearer-secret");

  assert.equal(basic, "provider failed: Authorization: Basic [REDACTED]");
  assert.equal(bearer, "provider failed: Authorization: Bearer [REDACTED]");
  assert.doesNotMatch(basic, /dXNlcjpwYXNz/);
  assert.doesNotMatch(bearer, /bearer-secret/);
});


test("server and Zalo client logs redact credential-bearing errors", async () => {
  const secrets = ["server-bearer-secret", "client-bearer-secret"];
  const captured = [];
  const originalError = console.error;
  const originalLog = console.log;
  console.error = (...args) => captured.push(args.map(String).join(" "));
  console.log = (...args) => captured.push(args.map(String).join(" "));
  try {
    await startRuntime({
      catalog: {},
      client: {
        api: {},
        login: async () => {
          throw new Error("Bearer " + secrets[0]);
        },
      },
      config: { forceQr: false, host: "127.0.0.1", port: 8787 },
      server: {
        once() {},
        listen(_port, _host, callback) {
          callback();
        },
      },
    });

    const listener = new EventEmitter();
    const zaloClient = new ZaloClient({
      credentialsPath: "unused-credentials.json",
      qrPath: "unused-qr.png",
    });
    zaloClient.api = { listener };
    zaloClient._wireListeners();
    listener.emit("error", new Error("Bearer " + secrets[1]));
  } finally {
    console.error = originalError;
    console.log = originalLog;
  }

  const output = captured.join("\n");
  for (const secret of secrets) assert.doesNotMatch(output, new RegExp(secret));
  assert.match(output, /Bearer \[REDACTED\]/i);
});
