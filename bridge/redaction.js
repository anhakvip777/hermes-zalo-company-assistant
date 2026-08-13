const SECRET_KEY = /(?:password|passwd|token|cookie|api[_-]?key|secret|imei|authorization)/i;
const AUTHORIZATION_SCHEME =
  /\b(Authorization[ \t]*:[ \t]*(?:Basic|Bearer)[ \t]+)[^\r\n,;]+/gi;
const BEARER = /\b(Bearer)[ \t]+[^\s,;'"\\]+/gi;
const AUTHORIZATION_ASSIGNMENT =
  /\b(authorization)(["']?\s*=\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}&#]+)/gi;
const ASSIGNMENT =
  /\b((?:[a-z0-9]+[_-])*[a-z0-9]*(?:password|passwd|token|cookie|api[_-]?key|secret|imei))(["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}&#]+)/gi;

function redactJsonText(value) {
  const trimmed = value.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== "object") return null;
    return JSON.stringify(redactSecrets(parsed));
  } catch {
    return null;
  }
}

export function redactText(value) {
  const text = String(value);
  const redactedJson = redactJsonText(text);
  if (redactedJson !== null) return redactedJson;
  return text
    .replace(AUTHORIZATION_SCHEME, "$1[REDACTED]")
    .replace(BEARER, "$1 [REDACTED]")
    .replace(AUTHORIZATION_ASSIGNMENT, "$1$2[REDACTED]")
    .replace(ASSIGNMENT, "$1$2[REDACTED]");
}

export function redactSecrets(value, seen = new WeakSet()) {
  if (typeof value === "string") return redactText(value);
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return "[CIRCULAR]";
  seen.add(value);
  if (Array.isArray(value)) {
    return value.map((item) => redactSecrets(item, seen));
  }
  const output = {};
  for (const [key, item] of Object.entries(value)) {
    output[key] = SECRET_KEY.test(key)
      ? "[REDACTED]"
      : redactSecrets(item, seen);
  }
  return output;
}

export function safeError(error) {
  return redactText(error && error.message ? error.message : error);
}
