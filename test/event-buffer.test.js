import assert from "node:assert/strict";
import test from "node:test";

import { EventBuffer, formatSseRecord } from "../bridge/event-buffer.js";


test("event buffer retains only its bounded tail", () => {
  const buffer = new EventBuffer({ capacity: 3, generation: "generation-a" });
  for (let index = 0; index < 5; index += 1) {
    buffer.publish("message", { index });
  }
  assert.deepEqual(
    buffer.recordsAfter().map((record) => record.id),
    ["generation-a:3", "generation-a:4", "generation-a:5"],
  );
});


test("event buffer replays strictly after Last-Event-ID", () => {
  const buffer = new EventBuffer({ capacity: 10, generation: "generation-a" });
  const first = buffer.publish("message", { index: 1 });
  buffer.publish("reaction", { index: 2 });
  buffer.publish("undo", { index: 3 });

  assert.equal(first.id, "generation-a:1");
  assert.deepEqual(
    buffer.recordsAfter("generation-a:1").map((record) => record.type),
    ["reaction", "undo"],
  );
  assert.equal(buffer.recordsAfter("invalid").length, 3);
  assert.equal(buffer.recordsAfter("generation-a:99").length, 3);
});


test("event buffer replays its retained tail when generation changes", () => {
  const buffer = new EventBuffer({ capacity: 10, generation: "new-generation" });
  buffer.publish("message", { index: 1 });
  buffer.publish("reaction", { index: 2 });

  assert.deepEqual(
    buffer.recordsAfter("old-generation:2").map((record) => record.id),
    ["new-generation:1", "new-generation:2"],
  );
});


test("event buffer treats legacy numeric cursor as fail-open", () => {
  const buffer = new EventBuffer({ capacity: 10, generation: "generation-a" });
  buffer.publish("message", { index: 1 });
  buffer.publish("reaction", { index: 2 });

  assert.deepEqual(
    buffer.recordsAfter("1").map((record) => record.id),
    ["generation-a:1", "generation-a:2"],
  );
});


test("SSE frame is valid and serializes one JSON data line", () => {
  const frame = formatSseRecord({
    id: 7,
    type: "message",
    payload: { text: "xin chào\nteam" },
  });
  assert.equal(
    frame,
    'id: 7\nevent: message\ndata: {"text":"xin chào\\nteam"}\n\n',
  );
});
