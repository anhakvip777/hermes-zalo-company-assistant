#!/usr/bin/env node

import { spawnSync } from "node:child_process";

const result = spawnSync(process.execPath, ["--test", ...process.argv.slice(2)], {
  cwd: process.cwd(),
  encoding: "utf8",
});

process.stdout.write(result.stdout || "");
process.stderr.write(result.stderr || "");

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
if (result.status !== 0) process.exit(result.status ?? 1);

const output = `${result.stdout || ""}\n${result.stderr || ""}`;
const count = /(?:^|\n)[ℹ#]\s*tests\s+(\d+)\s*$/m.exec(output);
if (!count || Number(count[1]) <= 0) {
  console.error("Node test guard failed: no tests were executed.");
  process.exit(1);
}
