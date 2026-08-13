import { randomUUID } from "node:crypto";


export function formatSseRecord(record) {
  return (
    "id: " + record.id +
    "\nevent: " + record.type +
    "\ndata: " + JSON.stringify(record.payload) +
    "\n\n"
  );
}

export class EventBuffer {
  constructor({ capacity = 200, heartbeatMs = 15000, generation = randomUUID() } = {}) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new Error("event buffer capacity must be a positive integer");
    }
    this.capacity = capacity;
    this.heartbeatMs = heartbeatMs;
    this.generation = String(generation);
    this.records = [];
    this.nextSequence = 1;
    this.clients = new Set();
  }

  get clientCount() {
    return this.clients.size;
  }

  publish(type, payload) {
    const sequence = this.nextSequence;
    const record = {
      id: `${this.generation}:${sequence}`,
      sequence,
      type: String(type || "message"),
      payload,
    };
    this.nextSequence += 1;
    this.records.push(record);
    if (this.records.length > this.capacity) this.records.shift();
    const frame = formatSseRecord(record);
    for (const response of [...this.clients]) {
      try {
        response.write(frame);
      } catch {
        this.clients.delete(response);
      }
    }
    return record;
  }

  recordsAfter(lastEventId) {
    if (typeof lastEventId !== "string") return [...this.records];
    const separator = lastEventId.lastIndexOf(":");
    if (separator <= 0) return [...this.records];

    const generation = lastEventId.slice(0, separator);
    const sequenceText = lastEventId.slice(separator + 1);
    if (!/^(0|[1-9]\d*)$/.test(sequenceText)) return [...this.records];

    const sequence = Number(sequenceText);
    if (
      generation !== this.generation ||
      !Number.isSafeInteger(sequence) ||
      sequence >= this.nextSequence
    ) {
      return [...this.records];
    }
    return this.records.filter((record) => record.sequence > sequence);
  }

  attach(req, res) {
    res.status(200);
    res.set({
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    res.flushHeaders?.();
    for (const record of this.recordsAfter(req.get("last-event-id"))) {
      res.write(formatSseRecord(record));
    }
    res.write(": connected\n\n");
    this.clients.add(res);
    const cleanup = () => {
      clearInterval(heartbeat);
      this.clients.delete(res);
    };
    const heartbeat = setInterval(() => {
      try {
        res.write(": heartbeat\n\n");
      } catch {
        cleanup();
      }
    }, this.heartbeatMs);
    heartbeat.unref?.();
    req.once("close", cleanup);
    res.once("close", cleanup);
    return cleanup;
  }

  closeAll() {
    for (const response of [...this.clients]) {
      try {
        response.end();
      } catch {
        // Connection already closed.
      }
    }
    this.clients.clear();
  }
}
