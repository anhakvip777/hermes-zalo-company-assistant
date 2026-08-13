import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ACTION_GROUP } from "../permissions.js";


export const SENSITIVE_METHODS = Object.freeze([
  "getCookie",
  "getContext",
  "getQR",
]);
const SENSITIVE_SET = new Set(SENSITIVE_METHODS);
const SENSITIVE_NORMALIZED = new Set(
  SENSITIVE_METHODS.map((method) => method.toLowerCase()),
);


function classified(method) {
  return Object.hasOwn(ACTION_GROUP, String(method));
}


function splitTopLevel(value) {
  const parts = [];
  let current = "";
  let quote = null;
  const depth = { "(": 0, "[": 0, "{": 0, "<": 0 };
  const closing = { ")": "(", "]": "[", "}": "{", ">": "<" };
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (quote) {
      current += character;
      if (character === quote && value[index - 1] !== "\\") quote = null;
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
      current += character;
      continue;
    }
    if (Object.hasOwn(depth, character)) {
      depth[character] += 1;
      current += character;
      continue;
    }
    if (Object.hasOwn(closing, character)) {
      depth[closing[character]] = Math.max(0, depth[closing[character]] - 1);
      current += character;
      continue;
    }
    if (
      character === "," &&
      Object.values(depth).every((valueAtDepth) => valueAtDepth === 0)
    ) {
      parts.push(current.trim());
      current = "";
      continue;
    }
    current += character;
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}


function balancedParentheses(source, start) {
  let depth = 0;
  let quote = null;
  for (let index = start; index < source.length; index += 1) {
    const character = source[index];
    if (quote) {
      if (character === quote && source[index - 1] !== "\\") quote = null;
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
      continue;
    }
    if (character === "(") depth += 1;
    if (character === ")") {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return -1;
}


function returnedSignature(declaration, methodName) {
  const marker = "export declare const " + methodName + "Factory";
  const start = declaration.indexOf(marker);
  if (start < 0) return null;
  const factoryArrow = declaration.indexOf("=>", start);
  if (factoryArrow < 0) return null;
  const open = declaration.indexOf("(", factoryArrow + 2);
  if (open < 0) return null;
  const close = balancedParentheses(declaration, open);
  if (close < 0) return null;
  const returnArrow = declaration.indexOf("=>", close + 1);
  if (returnArrow < 0) return null;
  const semicolon = declaration.indexOf(";", returnArrow + 2);
  return {
    parameterSource: declaration.slice(open + 1, close),
    returnType: declaration
      .slice(returnArrow + 2, semicolon < 0 ? declaration.length : semicolon)
      .trim(),
  };
}


function javascriptDefaults(jsSource, methodName) {
  const expression = new RegExp(
    "return\\s+(?:async\\s+)?function\\s+" +
      methodName +
      "\\s*\\(([^)]*)\\)",
  );
  const match = expression.exec(jsSource);
  if (!match) return new Map();
  const defaults = new Map();
  for (const part of splitTopLevel(match[1])) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const name = part.slice(0, separator).trim();
    defaults.set(name, part.slice(separator + 1).trim());
  }
  return defaults;
}


function parseParameters(source, defaults) {
  if (!source.trim()) return [];
  return splitTopLevel(source).map((part) => {
    const colon = part.indexOf(":");
    const rawName = (colon < 0 ? part : part.slice(0, colon)).trim();
    const optional = rawName.endsWith("?");
    const name = rawName.replace(/^\.\.\./, "").replace(/\?$/, "");
    return {
      name,
      type: colon < 0 ? "unknown" : part.slice(colon + 1).trim(),
      required: !optional && !defaults.has(name),
      default: defaults.get(name) ?? null,
    };
  });
}


function exampleValue(parameter, methodName) {
  const lower = parameter.name.toLowerCase();
  if (methodName === "createPoll" && parameter.name === "options") {
    return { question: "Đi ăn trưa?", options: ["A", "B"] };
  }
  if (lower === "message") return "xin chào";
  if (lower.includes("groupid")) return "group-id";
  if (lower.includes("threadid")) return "thread-id";
  if (lower.includes("userid") || lower === "uid") return "zalo-id";
  if (lower === "type") return "user";
  if (parameter.type.includes("boolean")) return false;
  if (parameter.type.includes("number")) return 0;
  if (parameter.type.includes("[]")) return [];
  if (parameter.type.includes("string")) return "value";
  return {};
}


function locateInstalledPackage() {
  const indexFile = fileURLToPath(import.meta.resolve("zca-js"));
  const distDir = path.dirname(indexFile);
  const packageDir = path.dirname(distDir);
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(packageDir, "package.json"), "utf8"),
  );
  return {
    version: packageJson.version,
    distDir,
    apisFile: path.join(distDir, "apis.d.ts"),
    apiDir: path.join(distDir, "apis"),
  };
}


export class MethodCatalog {
  constructor({ version, methods, liveApi = null }) {
    this.version = String(version);
    this.methods = new Map(methods.map((method) => [method.name, method]));
    this.liveApi = liveApi;
  }

  static fromInstalledPackage({ liveApi = null } = {}) {
    const located = locateInstalledPackage();
    const apiDeclaration = fs.readFileSync(located.apisFile, "utf8");
    const names = [
      ...apiDeclaration.matchAll(
        /^\s+([A-Za-z][A-Za-z0-9_]*): ReturnType</gm,
      ),
    ].map((match) => match[1]);
    const methods = [];
    for (const name of names) {
      if (SENSITIVE_SET.has(name) || !classified(name)) continue;
      const dtsPath = path.join(located.apiDir, name + ".d.ts");
      const jsPath = path.join(located.apiDir, name + ".js");
      let signature = null;
      let parameters = [];
      if (fs.existsSync(dtsPath)) {
        const declaration = fs.readFileSync(dtsPath, "utf8");
        const parsed = returnedSignature(declaration, name);
        if (parsed) {
          const defaults = fs.existsSync(jsPath)
            ? javascriptDefaults(fs.readFileSync(jsPath, "utf8"), name)
            : new Map();
          parameters = parseParameters(parsed.parameterSource, defaults);
          signature =
            name +
            "(" +
            parsed.parameterSource.replace(/\s+/g, " ").trim() +
            "): " +
            parsed.returnType.replace(/\s+/g, " ").trim();
        }
      }
      const args = parameters.map((parameter) => exampleValue(parameter, name));
      methods.push({
        name,
        category: ACTION_GROUP[name] || "other",
        description: "zca-js " + located.version + " method " + name,
        signature: signature || name + "(...args)",
        parameters,
        supportsNamedParams:
          parameters.length > 0 &&
          parameters.every((parameter) => /^[A-Za-z_$]\w*$/.test(parameter.name)),
        example: { action: "call", method: name, args },
      });
    }
    return new MethodCatalog({
      version: located.version,
      methods,
      liveApi,
    });
  }

  isSensitive(method) {
    return SENSITIVE_NORMALIZED.has(String(method).trim().toLowerCase());
  }

  has(method) {
    const name = String(method);
    if (this.isSensitive(name)) return false;
    return (
      this.methods.has(name) ||
      Boolean(
        classified(name) &&
        this.liveApi &&
          Object.hasOwn(this.liveApi, name) &&
          typeof this.liveApi[name] === "function",
      )
    );
  }

  _liveDescription(name) {
    if (
      this.isSensitive(name) ||
      !classified(name) ||
      !/^[A-Za-z][A-Za-z0-9_]*$/.test(name) ||
      !this.liveApi ||
      !Object.hasOwn(this.liveApi, name) ||
      typeof this.liveApi[name] !== "function"
    ) {
      return null;
    }
    return {
      name,
      category: ACTION_GROUP[name] || "other",
      description: "live zca-js " + this.version + " method " + name,
      signature: name + "(...args)",
      parameters: [],
      supportsNamedParams: false,
      example: { action: "call", method: name, args: [] },
    };
  }

  list(query = "") {
    const needle = String(query || "").trim().toLowerCase();
    const available = new Map(this.methods);
    if (this.liveApi) {
      for (const name of Object.getOwnPropertyNames(this.liveApi)) {
        if (available.has(name)) continue;
        const description = this._liveDescription(name);
        if (description) available.set(name, description);
      }
    }
    return [...available.values()]
      .filter((method) => {
        if (!needle) return true;
        return (
          method.name.toLowerCase().includes(needle) ||
          method.category.toLowerCase().includes(needle) ||
          method.description.toLowerCase().includes(needle)
        );
      })
      .map(({ parameters: _parameters, ...summary }) => ({
        ...summary,
        parameterCount: _parameters.length,
      }))
      .sort((left, right) => left.name.localeCompare(right.name));
  }

  describe(method) {
    const name = String(method || "");
    if (this.isSensitive(name)) {
      throw new Error("method is not available through chat");
    }
    const description = this.methods.get(name) || this._liveDescription(name);
    if (!description) {
      throw new Error("unknown zca-js API method: " + name);
    }
    return structuredClone(description);
  }

  toArgs(method, body = {}) {
    const name = String(method || "");
    if (this.isSensitive(name)) {
      throw new Error("method is not available through chat");
    }
    if (Array.isArray(body.args)) return [...body.args];
    if (!body.params || typeof body.params !== "object" || Array.isArray(body.params)) {
      return [];
    }
    const description = this.methods.get(name);
    if (!description || !description.supportsNamedParams) {
      throw new Error(
        "named params are unavailable for " + name + "; pass positional args",
      );
    }
    const ordered = [];
    for (const parameter of description.parameters) {
      if (Object.hasOwn(body.params, parameter.name)) {
        ordered.push(body.params[parameter.name]);
      } else if (parameter.required) {
        throw new Error("missing required parameter: " + parameter.name);
      } else {
        ordered.push(undefined);
      }
    }
    while (ordered.length && ordered.at(-1) === undefined) ordered.pop();
    return ordered;
  }
}
