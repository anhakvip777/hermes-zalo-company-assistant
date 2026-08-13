import { EventEmitter, once } from "node:events";


export class FakeZaloClient extends EventEmitter {
  constructor() {
    super();
    this.loggedIn = true;
    this.sessionDead = false;
    this.sessionDeadReason = null;
    this.ownId = "bot-id";
    this.qrState = { status: "authenticated", image: null };
    this.calls = [];
    this.api = {
      sendMessage: async (...args) => ({ args, token: "must-not-leak" }),
      createPoll: async (...args) => ({ args }),
      customMethod: async (...args) => ({ args }),
      getCookie: () => ({ cookie: "secret-cookie" }),
      getContext: () => ({ imei: "secret-imei" }),
    };
  }

  async callRaw(method, args = []) {
    this.calls.push({ method, args });
    const fn = this.api[method];
    if (typeof fn !== "function") {
      throw new Error("unknown zca-js API method: " + method);
    }
    return await fn(...args);
  }

  async sendText(threadId, threadType, text, mentions, quote) {
    return this.callRaw("sendMessage", [
      { msg: text, mentions, quote },
      threadId,
      threadType,
    ]);
  }

  async sendCard(...args) {
    return this._record("sendCard", args);
  }

  async sendFriendRequest(...args) {
    return this._record("sendFriendRequest", args);
  }

  async acceptFriendRequest(...args) {
    return this._record("acceptFriendRequest", args);
  }

  async rejectFriendRequest(...args) {
    return this._record("rejectFriendRequest", args);
  }

  async createGroup(...args) {
    return this._record("createGroup", args);
  }

  async addUserToGroup(...args) {
    return this._record("addUserToGroup", args);
  }

  async removeUserFromGroup(...args) {
    return this._record("removeUserFromGroup", args);
  }

  async changeGroupName(...args) {
    return this._record("changeGroupName", args);
  }

  async addGroupDeputy(...args) {
    return this._record("addGroupDeputy", args);
  }

  async leaveGroup(...args) {
    return this._record("leaveGroup", args);
  }

  async createPoll(...args) {
    return this._record("createPoll", args);
  }

  _record(method, args) {
    this.calls.push({ method, args });
    return { method, args };
  }

  async relogin() {
    return { method: "qr" };
  }

  async shutdown() {
    this.loggedIn = false;
  }
}


export async function withServer(app, callback) {
  const server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  const baseUrl = "http://127.0.0.1:" + address.port;
  try {
    return await callback(baseUrl);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  }
}


export function authHeaders(token = "x".repeat(32)) {
  return { Authorization: "Bearer " + token };
}
