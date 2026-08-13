// install.mjs — one-shot, cross-platform installer for the Hermes Zalo plugin.
// Runs the same on macOS, Linux, and Windows (Node drives everything; only the
// service-manager step branches per-OS).
//
//   node install.mjs                 # full setup: deps → login → background service
//   node install.mjs --no-service    # deps → login only (run `npm start` yourself)
//   node install.mjs --relogin       # force a fresh QR login
//   node install.mjs --service-only  # (re)install just the background service
//
// After this, the end-user only needs:  hermes gateway setup  → choose Zalo.

import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dataDir, logDir, runtimeEnvPath } from "./paths.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const NO_SERVICE = has("--no-service");
const RELOGIN = has("--relogin");
const SERVICE_ONLY = has("--service-only");
const DRY_RUN = has("--dry-run");
const ASSUME_YES = has("--yes");
const FORCE = has("--force");

function optionValue(name) {
  const index = argv.indexOf(name);
  return index >= 0 && argv[index + 1] && !argv[index + 1].startsWith("--")
    ? argv[index + 1]
    : null;
}

const PLATFORM = process.platform; // 'darwin' | 'linux' | 'win32'
const NODE_BIN = process.execPath;
const SERVER_JS = path.join(__dirname, "server.js");
const LABEL = "com.hermes.zaloplugin";
let RUNTIME_ENV_FILE = null;

function log(msg) { console.log(msg); }
function step(n, msg) { console.log(`\n[${n}] ${msg}`); }
function die(msg) { console.error(`\n✗ ${msg}`); process.exit(1); }

function selectedHermesHome() {
  return path.resolve(
    optionValue("--hermes-home") ||
      process.env.HERMES_HOME ||
      path.join(os.homedir(), ".hermes"),
  );
}

function printDryRun() {
  const hermesHome = selectedHermesHome();
  const directory = path.resolve(
    process.env.ZALO_DATA_DIR || path.join(os.homedir(), ".hermes-zalo"),
  );
  const envFile = path.resolve(
    process.env.ZALO_RUNTIME_ENV_FILE || path.join(directory, "company.env"),
  );
  console.log("DRY-RUN: no files, config, credentials, login, or services will be changed.");
  console.log(`Hermes profile: ${hermesHome}`);
  console.log(`Plugin target: ${path.join(hermesHome, "plugins", "zalo")}`);
  console.log(`Config target: ${path.join(hermesHome, "config.yaml")}`);
  console.log(`Runtime data: ${directory}`);
  console.log(`Runtime env: ${envFile}`);
  console.log(`Service install: ${NO_SERVICE ? "no" : "yes"}`);
  console.log(`Existing targets may be replaced: ${FORCE ? "yes" : "no"}`);
}

function installTargets() {
  const hermesHome = selectedHermesHome();
  return {
    hermesHome,
    pluginDir: path.join(hermesHome, "plugins", "zalo"),
    configPath: path.join(hermesHome, "config.yaml"),
  };
}

function preflightInstall() {
  const { pluginDir, configPath } = installTargets();
  if (fs.existsSync(pluginDir) && !FORCE) {
    die(`Plugin target already exists: ${pluginDir}. Re-run with --force to back it up and replace it.`);
  }
  if (fs.existsSync(configPath) && !FORCE) {
    die(`Hermes config already exists: ${configPath}. Re-run with --force to back it up before modification.`);
  }
}

function backupExistingTargets() {
  const { hermesHome, pluginDir, configPath } = installTargets();
  if (!fs.existsSync(pluginDir) && !fs.existsSync(configPath)) return null;
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "");
  const backupDir = path.join(hermesHome, "backups");
  fs.mkdirSync(backupDir, { recursive: true, mode: 0o700 });
  if (fs.existsSync(configPath)) {
    fs.copyFileSync(configPath, path.join(backupDir, `${stamp}-config.yaml`));
  }
  if (fs.existsSync(pluginDir)) {
    fs.cpSync(pluginDir, path.join(backupDir, `${stamp}-plugin`), {
      recursive: true,
      force: false,
      errorOnExist: true,
    });
  }
  log(`✓ Backup created: ${backupDir}`);
  return backupDir;
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd: __dirname, ...opts });
  if (r.status !== 0) die(`command failed: ${cmd} ${args.join(" ")}`);
  return r;
}

// ── 0. Prerequisites ────────────────────────────────────────────────────────
function checkPrereqs() {
  // Node version
  const major = parseInt(process.versions.node.split(".")[0], 10);
  if (major < 22) {
    die(
      `Node >= 22 required (found ${process.version}).\n` +
      `  Install Node:\n` +
      `    macOS:    brew install node   (or https://nodejs.org)\n` +
      `    Linux:    use nvm (https://github.com/nvm-sh/nvm) or your distro's nodejs package\n` +
      `    Windows:  https://nodejs.org (LTS installer)`
    );
  }
  log(`✓ Node ${process.version}`);

  // npm must be on PATH (it ships with Node, but some minimal installs strip it)
  const npmCmd = PLATFORM === "win32" ? "npm.cmd" : "npm";
  const probe = spawnSync(npmCmd, ["--version"], { stdio: "ignore", shell: PLATFORM === "win32" });
  if (probe.status !== 0) {
    die(
      "npm not found on PATH. It normally ships with Node.js.\n" +
      "  Reinstall Node from https://nodejs.org, or ensure npm is on your PATH."
    );
  }
  log("✓ npm available");
}

function ensureRuntimeEnvironment() {
  const directory = dataDir();
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  try { fs.chmodSync(directory, 0o700); } catch {}
  RUNTIME_ENV_FILE = runtimeEnvPath();
  const existing = fs.existsSync(RUNTIME_ENV_FILE)
    ? fs.readFileSync(RUNTIME_ENV_FILE, "utf8")
    : "";
  const tokenMatch = /^ZALO_PLUGIN_TOKEN=(.+)$/m.exec(existing);
  const token = process.env.ZALO_PLUGIN_TOKEN || tokenMatch?.[1]?.trim() || randomBytes(32).toString("hex");
  const host = process.env.ZALO_PLUGIN_HOST || "127.0.0.1";
  const port = process.env.ZALO_PLUGIN_PORT || "8787";
  const values = {
    ZALO_PLUGIN_HOST: host,
    ZALO_PLUGIN_PORT: port,
    ZALO_PLUGIN_URL: process.env.ZALO_PLUGIN_URL || `http://${host}:${port}`,
    ZALO_PLUGIN_TOKEN: token,
    ZALO_DATA_DIR: process.env.ZALO_DATA_DIR || directory,
  };
  const preserved = existing
    .split(/\r?\n/)
    .filter((line) => line && !Object.keys(values).some((key) => line.startsWith(key + "=")));
  const rendered = [
    "# Private runtime environment for Hermes Zalo company assistant",
    ...preserved.filter((line) => !line.startsWith("# Private runtime environment")),
    ...Object.entries(values).map(([key, value]) => `${key}=${value}`),
    "",
  ].join("\n");
  fs.writeFileSync(RUNTIME_ENV_FILE, rendered, { encoding: "utf8", mode: 0o600 });
  try { fs.chmodSync(RUNTIME_ENV_FILE, 0o600); } catch {}
  Object.assign(process.env, values, { ZALO_RUNTIME_ENV_FILE: RUNTIME_ENV_FILE });
  log(`✓ Private runtime env ready: ${RUNTIME_ENV_FILE}`);
}

// ── 1. Install dependencies (pulls zca-js from npm — no build, no bun) ───────
function installDeps() {
  // When installed as an npm package (global or npx), deps are already present —
  // skip. Only run `npm install` from a source checkout missing node_modules.
  const haveDeps = fs.existsSync(path.join(__dirname, "node_modules", "zca-js"));
  if (haveDeps) {
    log("✓ Dependencies already present (skipping npm install)");
    return;
  }
  step(1, "Installing dependencies (npm install)…");
  // npm is cross-platform; on Windows the shell needs npm.cmd via shell:true.
  run(PLATFORM === "win32" ? "npm.cmd" : "npm", ["install", "--no-audit", "--no-fund"], {
    shell: PLATFORM === "win32",
  });
  log("✓ Dependencies installed");
}

// ── 2. Log in (QR) unless we already have working credentials ────────────────
function login() {
  step(2, "Zalo login…");
  const args = [path.join(__dirname, "login.mjs")];
  if (RELOGIN) args.push("--force");
  run(NODE_BIN, args);
}

// ── 3. Background service (per-OS) ───────────────────────────────────────────
function installServiceDarwin() {
  const plistDir = path.join(os.homedir(), "Library", "LaunchAgents");
  fs.mkdirSync(plistDir, { recursive: true });
  const plistPath = path.join(plistDir, `${LABEL}.plist`);
  const logs = logDir();
  const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${NODE_BIN}</string>
    <string>${SERVER_JS}</string>
  </array>
  <key>WorkingDirectory</key><string>${__dirname}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${path.join(logs, "bridge.out.log")}</string>
  <key>StandardErrorPath</key><string>${path.join(logs, "bridge.err.log")}</string>
</dict>
</plist>
`;
  fs.writeFileSync(plistPath, plist);
  // reload (ignore failures if not yet loaded)
  spawnSync("launchctl", ["unload", plistPath], { stdio: "ignore" });
  run("launchctl", ["load", plistPath]);
  log(`✓ launchd service installed: ${plistPath}`);
  log("  Manage: launchctl unload/load the plist above.");
}

function installServiceLinux() {
  const unitDir = path.join(os.homedir(), ".config", "systemd", "user");
  fs.mkdirSync(unitDir, { recursive: true });
  const unitPath = path.join(unitDir, `${LABEL}.service`);
  const unit = `[Unit]
Description=Hermes Zalo Plugin
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${__dirname}
EnvironmentFile=${RUNTIME_ENV_FILE}
ExecStart=${NODE_BIN} ${SERVER_JS}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
`;
  fs.writeFileSync(unitPath, unit);
  const sysctl = (args) => spawnSync("systemctl", ["--user", ...args], { stdio: "inherit" });
  if (spawnSync("systemctl", ["--version"], { stdio: "ignore" }).status !== 0) {
    log(`⚠ systemd not available. Unit written to ${unitPath}; start the bridge manually with: npm start`);
    return;
  }
  sysctl(["daemon-reload"]);
  sysctl(["enable", "--now", `${LABEL}.service`]);
  log(`✓ systemd user service installed & started: ${unitPath}`);
  log(`  Manage: systemctl --user status/restart/stop ${LABEL}`);
  log("  Tip: run `loginctl enable-linger $USER` so it runs without an active login session.");
}

function installServiceWindows() {
  // Scheduled Task that runs at logon and restarts on failure. Avoids needing
  // nssm/admin service install. Uses schtasks (present on all Windows).
  const taskName = "HermesZaloPlugin";
  // Wrap in a tiny launcher so cwd is correct.
  const cmd = `"${NODE_BIN}" "${SERVER_JS}"`;
  const args = [
    "/Create", "/F",
    "/SC", "ONLOGON",
    "/TN", taskName,
    "/TR", cmd,
    "/RL", "LIMITED",
  ];
  const r = spawnSync("schtasks", args, { stdio: "inherit" });
  if (r.status !== 0) {
    log("⚠ Could not register a Scheduled Task automatically. Start the bridge manually with: npm start");
    log("  Or create a task that runs at logon with command:");
    log(`    ${cmd}`);
    return;
  }
  log(`✓ Scheduled Task '${taskName}' registered (runs at logon).`);
  log(`  Start now:  schtasks /Run /TN ${taskName}`);
  log(`  Manage:     Task Scheduler → ${taskName}`);
}

function installService() {
  step(3, "Installing background service (auto-start + auto-restart)…");
  if (PLATFORM === "darwin") return installServiceDarwin();
  if (PLATFORM === "linux") return installServiceLinux();
  if (PLATFORM === "win32") return installServiceWindows();
  log(`⚠ Unsupported platform '${PLATFORM}' for auto-service. Run the bridge manually: npm start`);
}

// ── 4. Install the Hermes-side plugin so `hermes gateway` sees Zalo ──────────
// The bridge (Node) and the Hermes adapter (Python) are separate halves. The
// adapter lives under hermes-plugin/ in this package; copy it into the user's
// Hermes plugin dir (~/.hermes/plugins/zalo) and add "zalo" to plugins.enabled
// so the (untrusted) user plugin is allowed to load.
function installHermesPlugin() {
  step(4, "Installing the Hermes plugin (so `hermes gateway` sees Zalo)…");
  const src = path.join(__dirname, "hermes-plugin");
  if (!fs.existsSync(src)) {
    log("⚠ hermes-plugin/ not found in package — skipping (bridge still works standalone).");
    return;
  }
  const hermesHome = selectedHermesHome();
  if (!fs.existsSync(hermesHome)) {
    log(`⚠ Hermes home not found at ${hermesHome}. Is Hermes installed?`);
    log("  Skipping plugin install. After installing Hermes, re-run: npx hermes-zalo-plugin setup --service-only");
    return;
  }
  const dest = path.join(hermesHome, "plugins", "zalo");
  fs.mkdirSync(dest, { recursive: true });
  fs.cpSync(src, dest, { recursive: true, force: true });
  log(`✓ Plugin copied to ${dest}`);

  // Enable the plugin in config.yaml (plugins.enabled must contain "zalo").
  const cfgPath = path.join(hermesHome, "config.yaml");
  try {
    const enabled = enableZaloInConfig(cfgPath);
    log(enabled === "already" ? "✓ Plugin already enabled in config.yaml"
        : enabled === "added" ? '✓ Added "zalo-platform" to plugins.enabled in config.yaml'
        : '✓ Created plugins.enabled with "zalo-platform" in config.yaml');
  } catch (e) {
    log(`⚠ Could not auto-enable the plugin: ${e.message}`);
    log('  Manually add "zalo-platform" under plugins.enabled in ~/.hermes/config.yaml');
  }
}

// Minimal, robust YAML editor for the one thing we need: ensure
// plugins.enabled contains "zalo". Operates line-by-line to avoid a YAML dep.
// Returns "already" | "added" | "created".
function enableZaloInConfig(cfgPath) {
  const text = fs.existsSync(cfgPath) ? fs.readFileSync(cfgPath, "utf-8") : "";
  const lines = text.split("\n");

  // Find a top-level "plugins:" line (no leading whitespace).
  let pluginsIdx = lines.findIndex((l) => /^plugins:\s*$/.test(l));
  if (pluginsIdx === -1) {
    // No plugins block — append a fresh one.
    const sep = text.length && !text.endsWith("\n") ? "\n" : "";
    fs.writeFileSync(cfgPath, text + sep + "\nplugins:\n  enabled:\n    - zalo-platform\n");
    return "created";
  }

  // Within the plugins block, find "enabled:" (2-space indent).
  let i = pluginsIdx + 1;
  let enabledIdx = -1;
  for (; i < lines.length; i++) {
    if (/^\S/.test(lines[i]) && lines[i].trim() !== "") break; // left the block
    if (/^\s+enabled:/.test(lines[i])) { enabledIdx = i; break; }
  }

  if (enabledIdx === -1) {
    // plugins: exists but no enabled: — insert one right after plugins:.
    lines.splice(pluginsIdx + 1, 0, "  enabled:", "    - zalo-platform");
    fs.writeFileSync(cfgPath, lines.join("\n"));
    return "added";
  }

  // enabled: may be inline ([a, b]) or a block list. Scan following list items.
  const inline = lines[enabledIdx].match(/enabled:\s*\[(.*)\]/);
  if (inline) {
    if (/(^|[,\s])zalo-platform([,\s]|$)/.test(inline[1])) return "already";
    const items = inline[1].trim();
    lines[enabledIdx] = lines[enabledIdx].replace(
      /enabled:\s*\[.*\]/,
      `enabled: [${items ? items + ", " : ""}zalo-platform]`,
    );
    fs.writeFileSync(cfgPath, lines.join("\n"));
    return "added";
  }

  // Block list: check the indented "- " items below enabled:. Track the last
  // real list item so we insert right after it (not after trailing blanks).
  let lastItem = enabledIdx;
  for (let j = enabledIdx + 1; j < lines.length; j++) {
    if (/^\s*-\s*zalo-platform\s*$/.test(lines[j])) return "already";
    if (/^\s*-\s/.test(lines[j])) { lastItem = j; continue; }
    if (lines[j].trim() === "") continue; // skip blank lines within/after the list
    break; // a non-list, non-blank line ends the list
  }
  lines.splice(lastItem + 1, 0, "    - zalo-platform");
  fs.writeFileSync(cfgPath, lines.join("\n"));
  return "added";
}

function nextSteps() {
  const port = process.env.ZALO_PLUGIN_PORT || "8787";
  console.log(`
────────────────────────────────────────────────────────
✓ Zalo plugin is set up.

  Bridge URL:  http://127.0.0.1:${port}
  Health:      hermes-zalo-plugin status

Next, register Zalo in Hermes:
  1) hermes gateway setup     → choose "Zalo" (🇻🇳)
  2) hermes gateway           → start relaying

The background service keeps the bridge running and restarts it on crash
or reboot, so you only do the login + setup once.
────────────────────────────────────────────────────────
`);
}

function banner() {
  // ANSI colors only when stdout is a TTY (avoid junk in logs/pipes).
  const tty = process.stdout.isTTY;
  const c = (code, s) => (tty ? `\x1b[${code}m${s}\x1b[0m` : s);
  const blue = (s) => c("38;5;33", s);   // Zalo blue
  const cyan = (s) => c("36", s);
  const dim = (s) => c("2", s);
  console.log(
    "\n" +
    blue("  ╦ ╦┌─┐┬─┐┌┬┐┌─┐┌─┐  ") + cyan("╔═╗┌─┐┬  ┌─┐") + "\n" +
    blue("  ╠═╣├┤ ├┬┘│││├┤ └─┐  ") + cyan("╔═╝├─┤│  │ │") + "\n" +
    blue("  ╩ ╩└─┘┴└─┴ ┴└─┘└─┘  ") + cyan("╚═╝┴ ┴┴─┘└─┘") + "\n" +
    dim("  Hermes × Zalo plugin") + "\n" +
    dim("  chat with your Hermes agent from Zalo") + "\n",
  );
}

async function main() {
  banner();
  console.log("Hermes Zalo Plugin — installer");
  console.log("(Safe to re-run: deps are upserted, login is skipped if already logged in,");
  console.log(" and the background service is re-registered cleanly.)\n");
  if (DRY_RUN) {
    printDryRun();
    return;
  }
  if (!ASSUME_YES) {
    die("Refusing side effects without explicit confirmation. Re-run with --yes, or inspect first with --dry-run.");
  }
  process.env.HERMES_HOME = selectedHermesHome();
  preflightInstall();
  checkPrereqs();
  ensureRuntimeEnvironment();

  if (SERVICE_ONLY) {
    backupExistingTargets();
    installHermesPlugin();
    if (!NO_SERVICE) installService();
    nextSteps();
    return;
  }

  installDeps();
  login();
  backupExistingTargets();
  installHermesPlugin();
  if (!NO_SERVICE) installService();
  else log("\n(Skipping background service — run `npm start` to launch the bridge.)");
  nextSteps();
}

main().catch((e) => die(e?.message || String(e)));
