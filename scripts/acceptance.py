#!/usr/bin/env python3
"""Small, inspectable release gate for the company-assistant plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def command(name: str, argv: list[str]) -> dict:
    executable = list(argv)
    if os.name == "nt" and executable and executable[0] == "npm":
        executable[0] = "npm.cmd"
    completed = subprocess.run(executable, cwd=ROOT, capture_output=True, text=True)
    return {
        "name": name,
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def changed_paths() -> set[str]:
    paths: set[str] = set()
    commands = [
        ["git", "diff", "--name-only", "--relative"],
        ["git", "diff", "--cached", "--name-only", "--relative"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    for argv in commands:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "git status failed")
        paths.update(
            line.strip().replace("\\", "/")
            for line in completed.stdout.splitlines()
            if line.strip()
        )
    return paths


def manifest_check() -> dict:
    manifest = ROOT / "docs" / "architecture" / "file-manifest.md"
    missing: list[str] = []
    registered: set[str] = set()
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
            if not match:
                continue
            path = match.group(1).replace("\\", "/")
            registered.add(path)
            if not (ROOT / path).exists():
                missing.append(path)
    else:
        missing.append(str(manifest.relative_to(ROOT)))
    try:
        unexpected = sorted(changed_paths() - registered)
        error = None
    except RuntimeError as exc:
        unexpected = []
        error = str(exc)
    return {
        "name": "file_manifest",
        "ok": not missing and not unexpected and error is None,
        "missing": missing,
        "unexpected": unexpected,
        "error": error,
    }


def continuity_check() -> dict:
    required = [
        "AGENTS.md",
        "docs/architecture/system-overview.md",
        "docs/architecture/database-schema.md",
        "docs/architecture/file-manifest.md",
        "docs/superpowers/specs/2026-08-10-hermes-zalo-admin-web-ui-design.md",
        "docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md",
        "hermes-plugin/migrations/001_initial.sql",
    ]
    missing = [name for name in required if not (ROOT / name).exists()]
    expected = None
    actual = None
    schema_doc = ROOT / "docs" / "architecture" / "database-schema.md"
    migration = ROOT / "hermes-plugin" / "migrations" / "001_initial.sql"
    if schema_doc.exists():
        match = re.search(
            r"SHA-256 khóa[^\n]*\n`([0-9a-f]{64})`",
            schema_doc.read_text(encoding="utf-8"),
            flags=re.IGNORECASE,
        )
        expected = match.group(1).lower() if match else None
    if migration.exists():
        actual = hashlib.sha256(migration.read_bytes()).hexdigest()
    ok = not missing and expected is not None and actual == expected
    return {
        "name": "session_continuity",
        "ok": ok,
        "missing": missing,
        "migration_expected": expected,
        "migration_actual": actual,
    }


def compile_python() -> dict:
    failures: list[str] = []
    for path in (ROOT / "hermes-plugin").glob("*.py"):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path}: {exc.msg}")
    return {"name": "python_compile", "ok": not failures, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--full",
        action="store_true",
        help="deprecated alias; the default acceptance run is already full",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="only check manifest and Python compilation",
    )
    args = parser.parse_args()

    checks = [continuity_check(), manifest_check(), compile_python()]
    if args.full or not args.static:
        checks.extend(
            [
                command("node_tests", ["npm", "test"]),
                command("python_tests", [sys.executable, "-m", "pytest", "-q"]),
            ]
        )
    result = {"ok": all(item.get("ok", False) for item in checks), "checks": checks}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(("PASS" if item["ok"] else "FAIL") + " " + item["name"])
        print("acceptance: " + ("PASS" if result["ok"] else "FAIL"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
