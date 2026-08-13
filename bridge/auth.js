import crypto from "node:crypto";

function digest(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest();
}

function tokenFromRequest(req) {
  const authorization = String(req.get("authorization") || "");
  const match = /^Bearer[ \t]+(.+)$/i.exec(authorization);
  if (match) return match[1].trim();
  const legacy = req.get("x-bridge-token");
  return legacy === undefined ? "" : String(legacy);
}

export function createBridgeAuth(expectedToken) {
  const token = String(expectedToken || "");
  if (Buffer.byteLength(token, "utf8") < 32) {
    throw new Error("bridge auth token must contain at least 32 UTF-8 bytes");
  }
  const expectedDigest = digest(token);
  return function bridgeAuth(req, res, next) {
    const providedDigest = digest(tokenFromRequest(req));
    if (!crypto.timingSafeEqual(expectedDigest, providedDigest)) {
      res.status(401).json({ error: "bridge authentication required" });
      return;
    }
    next();
  };
}
