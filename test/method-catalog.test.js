import assert from "node:assert/strict";
import test from "node:test";

import {
  MethodCatalog,
  SENSITIVE_METHODS,
} from "../bridge/method-catalog.js";


test("catalog is generated from zca-js 2.1.2 and hides credential methods", () => {
  const catalog = MethodCatalog.fromInstalledPackage();
  const all = catalog.list();
  const names = new Set(all.map((entry) => entry.name));

  assert.equal(catalog.version, "2.1.2");
  assert.ok(all.length >= 140, "expected broad zca-js surface, got " + all.length);
  assert.ok(names.has("sendMessage"));
  assert.ok(names.has("createPoll"));
  for (const method of SENSITIVE_METHODS) {
    assert.equal(names.has(method), false);
  }
});


test("describe returns parameter order, TypeScript signature, defaults, and example", () => {
  const catalog = MethodCatalog.fromInstalledPackage();
  const description = catalog.describe("createPoll");

  assert.equal(description.name, "createPoll");
  assert.deepEqual(
    description.parameters.map((parameter) => parameter.name),
    ["options", "groupId"],
  );
  assert.match(description.signature, /CreatePollOptions/);
  assert.ok(Array.isArray(description.example.args));
  assert.equal(description.supportsNamedParams, true);
});


test("named params are ordered by catalog and positional args are fallback", () => {
  const catalog = MethodCatalog.fromInstalledPackage();
  const options = { question: "Đi ăn trưa?", options: ["A", "B"] };

  assert.deepEqual(
    catalog.toArgs("createPoll", {
      params: { groupId: "g-1", options },
    }),
    [options, "g-1"],
  );
  assert.deepEqual(
    catalog.toArgs("customMethod", { args: [1, "group"] }),
    [1, "group"],
  );
  assert.throws(
    () => catalog.describe("getCookie"),
    /not available/i,
  );
});


test("live API discovery only exposes explicitly classified own methods", () => {
  const liveApi = Object.create({ inheritedMethod() {} });
  liveApi.sendMessage = () => null;
  liveApi.futureUnknownMethod = () => null;
  const catalog = new MethodCatalog({ version: "test", methods: [], liveApi });

  assert.equal(catalog.has("sendMessage"), true);
  assert.equal(catalog.has("futureUnknownMethod"), false);
  assert.equal(catalog.has("inheritedMethod"), false);
  assert.equal(catalog.has("toString"), false);
  assert.ok(catalog.list().some((method) => method.name === "sendMessage"));
  assert.equal(catalog.describe("sendMessage").supportsNamedParams, false);
  assert.throws(() => catalog.describe("futureUnknownMethod"), /unknown/i);
});


test("sensitive method matching is case-insensitive and rejects variants", () => {
  const liveApi = {
    getCookie() {},
    GETCOOKIE() {},
    getContext() {},
    GetQr() {},
  };
  const catalog = new MethodCatalog({ version: "test", methods: [], liveApi });

  for (const method of ["getCookie", "GETCOOKIE", "GetContext", "getqr", " GetQR "]) {
    assert.equal(catalog.isSensitive(method), true);
    assert.equal(catalog.has(method), false);
    assert.throws(() => catalog.describe(method), /not available/i);
  }
});
