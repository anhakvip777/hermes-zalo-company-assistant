#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const argv = process.argv.slice(2);
const allowDirty = argv.includes("--allow-dirty");
const ciRelease = argv.includes("--ci-release");
const HERMES_VERSION = "0.19.0";
const HERMES_COMMIT = "eb52760564dbba2e5971fa54bd67384e281cd3b8";
const HERMES_REQUIRED_CONTRACTS = [
  "PlatformEntry.env_enablement_fn",
  "MessageEvent.channel_context",
];

function optionValue(name, fallback = null) {
  const index = argv.indexOf(name);
  return index >= 0 && argv[index + 1] && !argv[index + 1].startsWith("--")
    ? argv[index + 1]
    : fallback;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(`${command} failed: ${result.stderr || result.stdout || result.error}`);
  }
  return result.stdout.trim();
}

function sha256(file) {
  return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

const gitProbe = spawnSync("git", ["rev-parse", "--is-inside-work-tree"], {
  cwd: ROOT,
  encoding: "utf8",
});
if (gitProbe.status !== 0 || gitProbe.stdout.trim() !== "true") {
  console.error(
    "This source archive does not contain Git provenance. Build an official release " +
    "from the reviewed Git checkout; use the supplied manifest and checksums only " +
    "to audit an existing archive.",
  );
  process.exit(2);
}

const status = run("git", ["status", "--porcelain"]);
if (status && !allowDirty && !ciRelease) {
  console.error("Working tree is not clean. Commit/tag the reviewed source first, or use --allow-dirty for a clearly marked pre-release audit bundle.");
  process.exit(2);
}

const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
const version = packageJson.version;
const commit = run("git", ["rev-parse", "HEAD"]);
const tag = run("git", ["tag", "--points-at", "HEAD"]);
const tags = tag ? tag.split(/\r?\n/) : [];
const expectedTag = `v${version}`;
if (ciRelease) {
  let attestedCommit = "";
  let tagCommit = "";
  try {
    attestedCommit = run("git", ["rev-parse", `${process.env.GITHUB_SHA}^{commit}`]);
    tagCommit = run("git", ["rev-list", "-n", "1", process.env.GITHUB_REF_NAME || ""]);
  } catch {
    // The shared attestation failure below is intentionally secret-safe.
  }
  const attested = process.env.GITHUB_REF_NAME === expectedTag
    && attestedCommit === commit
    && tagCommit === commit
    && Boolean(process.env.GITHUB_REPOSITORY)
    && Boolean(process.env.GITHUB_RUN_ID);
  if (!attested) {
    console.error("CI release attestation failed: tag, commit, repository, or run ID does not match.");
    process.exit(2);
  }
} else if (!allowDirty && !tags.includes(expectedTag)) {
  console.error(
    `An official release must be built from tag ${expectedTag} at HEAD. ` +
    "Create and push the reviewed version tag, or use --allow-dirty for a pre-release audit bundle.",
  );
  process.exit(2);
}
const output = path.resolve(optionValue("--output", path.join(ROOT, "release")));
fs.mkdirSync(output, { recursive: true });

const temp = fs.mkdtempSync(path.join(os.tmpdir(), "hermes-zalo-release-"));
try {
  const npmCli = process.env.npm_execpath || path.join(
    path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js",
  );
  const packed = JSON.parse(
    run(process.execPath, [npmCli, "pack", "--pack-destination", temp, "--json"]),
  )[0];
  const runtimeName = `hermes-zalo-company-${version}-runtime.tgz`;
  const runtimePath = path.join(output, runtimeName);
  fs.copyFileSync(path.join(temp, packed.filename), runtimePath);

  const sourceName = `hermes-zalo-company-${version}-source-audit.tgz`;
  const sourcePath = path.join(output, sourceName);
  run("git", ["archive", "--format=tar.gz", `--output=${sourcePath}`, "HEAD"]);

  const commandVersion = (command, args) => {
    try { return run(command, args).split(/\r?\n/)[0]; } catch { return "unavailable"; }
  };
  const manifest = {
    schema: "hermes-zalo-release-v1",
    generated_at: new Date().toISOString(),
    release_status: ciRelease || (!allowDirty && !status) ? "release-clean" : "pre-release-dirty",
    version,
    git: { commit, tags, clean: !status },
    compatibility: {
      hermes_agent: {
        version: HERMES_VERSION,
        commit: HERMES_COMMIT,
        required_contracts: HERMES_REQUIRED_CONTRACTS,
      },
      zca_js: packageJson.dependencies["zca-js"],
      node: process.version,
      python: commandVersion("python", ["--version"]),
      os: `${os.platform()} ${os.release()} ${os.arch()}`,
    },
    verification: {
      expected_node_tests: 65,
      expected_python_tests_including_integration: 202,
      expected_integration_subset: 17,
      ci_evidence: !ciRelease && (allowDirty || status)
        ? { status: "not-available", reason: "dirty pre-release" }
        : process.env.GITHUB_SERVER_URL && process.env.GITHUB_REPOSITORY && process.env.GITHUB_RUN_ID
          ? {
              status: "available",
              run_id: process.env.GITHUB_RUN_ID,
              url: `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`,
            }
          : { status: "pending", reason: "attach CI URL/run ID for this commit/tag" },
    },
    artifacts: {
      runtime: { file: runtimeName, sha256: sha256(runtimePath), bytes: fs.statSync(runtimePath).size },
      source_audit: { file: sourceName, sha256: sha256(sourcePath), bytes: fs.statSync(sourcePath).size },
    },
  };
  const manifestPath = path.join(output, `hermes-zalo-company-${version}-manifest.json`);
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ manifest: manifestPath, ...manifest.artifacts }, null, 2));
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
