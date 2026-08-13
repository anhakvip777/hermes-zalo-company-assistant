import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import os from "node:os";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadBridgeConfig } from "../bridge/config.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("npm package includes the documented Python dependency files", () => {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(ROOT, "package.json"), "utf8"),
  );
  assert.ok(packageJson.files.includes("requirements-test.txt"));
  assert.ok(packageJson.files.includes("requirements-runtime.txt"));
  assert.ok(packageJson.files.includes("pyproject.toml"));
});


test("npm test uses a zero-test guard", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  assert.equal(packageJson.scripts.test, "node scripts/run-node-tests.mjs");
});


test("release builder refuses an uncommitted production release without explicit override", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-release-builder-"));
  try {
    const result = spawnSync(
      process.execPath,
      [path.join(ROOT, "scripts", "build-release.mjs"), "--output", root],
      { cwd: ROOT, encoding: "utf8" },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr + result.stdout, /working tree|--allow-dirty/i);
    assert.deepEqual(fs.readdirSync(root), []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("release builder reports missing Git provenance clearly in a source archive", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-release-archive-"));
  const archiveRoot = path.join(root, "source");
  const scriptDir = path.join(archiveRoot, "scripts");
  fs.mkdirSync(scriptDir, { recursive: true });
  fs.copyFileSync(
    path.join(ROOT, "scripts", "build-release.mjs"),
    path.join(scriptDir, "build-release.mjs"),
  );
  try {
    const result = spawnSync(
      process.execPath,
      [path.join(scriptDir, "build-release.mjs"), "--output", path.join(root, "release")],
      { cwd: archiveRoot, encoding: "utf8" },
    );
    const output = result.stderr + result.stdout;
    assert.notEqual(result.status, 0);
    assert.match(output, /source archive.*Git provenance|Git provenance.*source archive/i);
    assert.doesNotMatch(output, /fatal: not a git repository|Error: git failed/i);
    assert.equal(fs.existsSync(path.join(root, "release")), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("release manifest pins the exact Hermes commit and required API contracts", () => {
  const source = fs.readFileSync(path.join(ROOT, "scripts", "build-release.mjs"), "utf8");
  assert.match(source, /eb52760564dbba2e5971fa54bd67384e281cd3b8/);
  assert.match(source, /PlatformEntry\.env_enablement_fn/);
  assert.match(source, /MessageEvent\.channel_context/);
  assert.doesNotMatch(source, /hermes_agent:\s*"0\.19\.0"/);
});


test("official release builder requires the version tag at HEAD", () => {
  const source = fs.readFileSync(path.join(ROOT, "scripts", "build-release.mjs"), "utf8");
  assert.match(source, /expectedTag\s*=\s*`v\$\{version\}`/);
  assert.match(source, /tags\.includes\(expectedTag\)/);
  assert.match(source, /official release.*tag|tag.*official release/i);
});


test("allow-dirty always labels the artifact as a pre-release", () => {
  const source = fs.readFileSync(path.join(ROOT, "scripts", "build-release.mjs"), "utf8");
  assert.match(
    source,
    /release_status:\s*ciRelease\s*\|\|\s*\(!allowDirty\s*&&\s*!status\)/,
  );
});


test("source audit bundle is built from the committed Git tree", () => {
  const source = fs.readFileSync(path.join(ROOT, "scripts", "build-release.mjs"), "utf8");
  assert.match(source, /git["'], \["archive", "--format=tar\.gz"/);
  assert.match(source, /"HEAD"/);
  assert.doesNotMatch(source, /run\("tar", \[/);
});


test("CI release mode requires an attested matching tag and commit", () => {
  const source = fs.readFileSync(path.join(ROOT, "scripts", "build-release.mjs"), "utf8");
  assert.match(source, /--ci-release/);
  assert.match(source, /GITHUB_REF_NAME/);
  assert.match(source, /GITHUB_SHA/);
  assert.match(source, /GITHUB_RUN_ID/);
  assert.match(source, /CI release attestation/i);
});


test("npm publishing is manual for this internal fork", () => {
  const workflow = fs.readFileSync(path.join(ROOT, ".github", "workflows", "publish.yml"), "utf8");
  assert.match(workflow, /workflow_dispatch/);
  assert.doesNotMatch(workflow, /push:\s*\n\s*tags:/);
});


test("CI checks out and tests against the pinned Hermes compatibility commit", () => {
  const workflow = fs.readFileSync(path.join(ROOT, ".github", "workflows", "ci.yml"), "utf8");
  assert.match(workflow, /NousResearch\/hermes-agent/);
  assert.match(workflow, /eb52760564dbba2e5971fa54bd67384e281cd3b8/);
  assert.match(workflow, /\.hermes-compat/);
  assert.match(workflow, /PYTHONPATH/);
});


test("CI builds and uploads official artifacts only from a version tag", () => {
  const workflow = fs.readFileSync(path.join(ROOT, ".github", "workflows", "ci.yml"), "utf8");
  assert.match(workflow, /tags:\s*\[?["']?v\*/);
  assert.match(workflow, /refs\/tags\/v/);
  assert.match(workflow, /node scripts\/build-release\.mjs --ci-release/);
  assert.match(workflow, /actions\/upload-artifact@v4/);
  assert.match(workflow, /GITHUB_RUN_ID/);
});


test("npm package and Hermes plugin publish the same version", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  const pluginYaml = fs.readFileSync(path.join(ROOT, "hermes-plugin", "plugin.yaml"), "utf8");
  const match = /^version:\s*([^\s]+)\s*$/m.exec(pluginYaml);
  assert.ok(match);
  assert.equal(packageJson.version, match[1]);
});


test("runtime package includes the npm shrinkwrap used by audit", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  assert.ok(packageJson.files.includes("npm-shrinkwrap.json"));
});


test("npm dry-run artifact contains a reproducible dependency lock", () => {
  const npmCli = process.env.npm_execpath || path.join(
    path.dirname(process.execPath),
    "node_modules",
    "npm",
    "bin",
    "npm-cli.js",
  );
  const result = spawnSync(process.execPath, [npmCli, "pack", "--dry-run", "--json"], {
    cwd: ROOT,
    encoding: "utf8",
    shell: false,
  });
  assert.equal(result.status, 0, result.stderr);
  const metadata = JSON.parse(result.stdout)[0];
  const paths = new Set(metadata.files.map((entry) => entry.path));
  assert.ok(paths.has("npm-shrinkwrap.json") || paths.has("package-lock.json"));
});


test("bridge config requires a token with at least 32 UTF-8 bytes", () => {
  assert.throws(
    () => loadBridgeConfig({ ZALO_PLUGIN_TOKEN: "short" }),
    /32/,
  );
  assert.throws(
    () => loadBridgeConfig({}),
    /ZALO_PLUGIN_TOKEN/,
  );
  assert.equal(
    loadBridgeConfig({ ZALO_PLUGIN_TOKEN: "x".repeat(32) }).token,
    "x".repeat(32),
  );
});


test("bridge config is loopback-only", () => {
  assert.throws(
    () =>
      loadBridgeConfig({
        ZALO_PLUGIN_TOKEN: "x".repeat(32),
        ZALO_PLUGIN_HOST: "0.0.0.0",
      }),
    /127\.0\.0\.1/,
  );
  assert.equal(
    loadBridgeConfig({
      ZALO_PLUGIN_TOKEN: "x".repeat(32),
      ZALO_PLUGIN_HOST: "127.0.0.1",
    }).host,
    "127.0.0.1",
  );
});


test("bridge config rejects invalid ports", () => {
  for (const port of ["0", "65536", "abc"]) {
    assert.throws(
      () =>
        loadBridgeConfig({
          ZALO_PLUGIN_TOKEN: "x".repeat(32),
          ZALO_PLUGIN_PORT: port,
        }),
      /port/i,
    );
  }
});


test("bridge config provides a bounded provider request deadline", () => {
  const base = { ZALO_PLUGIN_TOKEN: "x".repeat(32) };
  assert.equal(loadBridgeConfig(base).requestTimeoutMs, 55_000);
  assert.equal(
    loadBridgeConfig({
      ...base,
      ZALO_REQUEST_TIMEOUT_MS: "120000",
    }).requestTimeoutMs,
    120_000,
  );
  for (const value of ["0", "99", "600001", "abc"]) {
    assert.throws(
      () => loadBridgeConfig({ ...base, ZALO_REQUEST_TIMEOUT_MS: value }),
      /timeout/i,
    );
  }
});


test("Windows task registration does not reparse paths through cmd.exe", () => {
  const source = readFileSync(new URL("../install.mjs", import.meta.url), "utf8");
  const start = source.indexOf("function installServiceWindows()");
  const end = source.indexOf("\nfunction installService()", start);
  const windowsInstaller = source.slice(start, end);

  assert.ok(start >= 0 && end > start);
  assert.doesNotMatch(windowsInstaller, /shell:\s*true/);
});


test("installer force overwrite does not imply QR relogin", () => {
  const source = readFileSync(new URL("../install.mjs", import.meta.url), "utf8");
  assert.match(source, /const RELOGIN = has\("--relogin"\)/);
  assert.doesNotMatch(source, /RELOGIN\s*=.*--force/);
});


test("installer dry-run reports changes without touching the target profile", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-installer-dry-run-"));
  const hermesHome = path.join(root, "profile");
  const dataDir = path.join(root, "data");
  try {
    const result = spawnSync(
      process.execPath,
      [path.join(ROOT, "install.mjs"), "--dry-run", "--hermes-home", hermesHome],
      {
        cwd: ROOT,
        env: { ...process.env, ZALO_DATA_DIR: dataDir },
        encoding: "utf8",
      },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /dry-run/i);
    assert.match(result.stdout, new RegExp(hermesHome.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.equal(fs.existsSync(hermesHome), false);
    assert.equal(fs.existsSync(dataDir), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("installer requires explicit confirmation before making changes", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-installer-confirm-"));
  try {
    const result = spawnSync(
      process.execPath,
      [path.join(ROOT, "install.mjs"), "--service-only", "--hermes-home", path.join(root, "profile")],
      {
        cwd: ROOT,
        env: { ...process.env, ZALO_DATA_DIR: path.join(root, "data") },
        encoding: "utf8",
      },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr + result.stdout, /--yes/i);
    assert.deepEqual(fs.readdirSync(root), []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("installer refuses to overwrite an existing plugin without force", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-installer-existing-"));
  const hermesHome = path.join(root, "profile");
  const pluginDir = path.join(hermesHome, "plugins", "zalo");
  fs.mkdirSync(pluginDir, { recursive: true });
  fs.writeFileSync(path.join(pluginDir, "marker.txt"), "keep", "utf8");
  fs.writeFileSync(path.join(hermesHome, "config.yaml"), "plugins:\n  enabled: []\n", "utf8");
  try {
    const result = spawnSync(
      process.execPath,
      [
        path.join(ROOT, "install.mjs"),
        "--service-only",
        "--no-service",
        "--yes",
        "--hermes-home",
        hermesHome,
      ],
      { cwd: ROOT, env: { ...process.env, ZALO_DATA_DIR: path.join(root, "data") }, encoding: "utf8" },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr + result.stdout, /--force/i);
    assert.equal(fs.readFileSync(path.join(pluginDir, "marker.txt"), "utf8"), "keep");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("installer refuses to modify an existing config without force", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-installer-config-"));
  const hermesHome = path.join(root, "profile");
  fs.mkdirSync(hermesHome, { recursive: true });
  fs.writeFileSync(path.join(hermesHome, "config.yaml"), "plugins:\n  enabled: []\n", "utf8");
  try {
    const result = spawnSync(
      process.execPath,
      [
        path.join(ROOT, "install.mjs"),
        "--service-only",
        "--no-service",
        "--yes",
        "--hermes-home",
        hermesHome,
      ],
      { cwd: ROOT, env: { ...process.env, ZALO_DATA_DIR: path.join(root, "data") }, encoding: "utf8" },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr + result.stdout, /config.*--force|--force.*config/i);
    assert.equal(
      fs.readFileSync(path.join(hermesHome, "config.yaml"), "utf8"),
      "plugins:\n  enabled: []\n",
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("forced install backs up existing config and plugin before replacement", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-installer-force-"));
  const hermesHome = path.join(root, "profile");
  const pluginDir = path.join(hermesHome, "plugins", "zalo");
  const configPath = path.join(hermesHome, "config.yaml");
  fs.mkdirSync(pluginDir, { recursive: true });
  fs.writeFileSync(path.join(pluginDir, "marker.txt"), "old-plugin", "utf8");
  fs.writeFileSync(configPath, "plugins:\n  enabled: []\n", "utf8");
  try {
    const result = spawnSync(
      process.execPath,
      [
        path.join(ROOT, "install.mjs"),
        "--service-only",
        "--no-service",
        "--yes",
        "--force",
        "--hermes-home",
        hermesHome,
      ],
      { cwd: ROOT, env: { ...process.env, ZALO_DATA_DIR: path.join(root, "data") }, encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr + result.stdout);
    const backups = fs.readdirSync(path.join(hermesHome, "backups"));
    const configBackup = backups.find((name) => name.endsWith("-config.yaml"));
    const pluginBackup = backups.find((name) => name.endsWith("-plugin"));
    assert.ok(configBackup);
    assert.ok(pluginBackup);
    assert.equal(
      fs.readFileSync(path.join(hermesHome, "backups", configBackup), "utf8"),
      "plugins:\n  enabled: []\n",
    );
    assert.equal(
      fs.readFileSync(path.join(hermesHome, "backups", pluginBackup, "marker.txt"), "utf8"),
      "old-plugin",
    );
    assert.equal(fs.existsSync(path.join(pluginDir, "plugin.yaml")), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("uninstaller dry-run and restore-backup recover the previous plugin and config", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-uninstall-restore-"));
  const hermesHome = path.join(root, "profile");
  const pluginDir = path.join(hermesHome, "plugins", "zalo");
  const backupDir = path.join(hermesHome, "backups");
  fs.mkdirSync(pluginDir, { recursive: true });
  fs.mkdirSync(path.join(backupDir, "20260813-plugin"), { recursive: true });
  fs.writeFileSync(path.join(pluginDir, "current.txt"), "current", "utf8");
  fs.writeFileSync(path.join(backupDir, "20260813-plugin", "old.txt"), "old", "utf8");
  fs.writeFileSync(path.join(hermesHome, "config.yaml"), "current-config\n", "utf8");
  fs.writeFileSync(path.join(backupDir, "20260813-config.yaml"), "old-config\n", "utf8");
  try {
    const dryRun = spawnSync(
      process.execPath,
      [path.join(ROOT, "uninstall.mjs"), "--dry-run", "--hermes-home", hermesHome],
      { cwd: ROOT, encoding: "utf8" },
    );
    assert.equal(dryRun.status, 0, dryRun.stderr);
    assert.match(dryRun.stdout, /dry-run/i);
    assert.equal(fs.readFileSync(path.join(pluginDir, "current.txt"), "utf8"), "current");

    const restore = spawnSync(
      process.execPath,
      [
        path.join(ROOT, "uninstall.mjs"),
        "--restore-backup",
        "20260813",
        "--yes",
        "--hermes-home",
        hermesHome,
      ],
      { cwd: ROOT, encoding: "utf8" },
    );
    assert.equal(restore.status, 0, restore.stderr + restore.stdout);
    assert.equal(fs.existsSync(path.join(pluginDir, "current.txt")), false);
    assert.equal(fs.readFileSync(path.join(pluginDir, "old.txt"), "utf8"), "old");
    assert.equal(fs.readFileSync(path.join(hermesHome, "config.yaml"), "utf8"), "old-config\n");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
