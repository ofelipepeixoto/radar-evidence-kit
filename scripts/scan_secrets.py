#!/usr/bin/env python3
"""Original Radar proposal: scan committed history without trusting PR policy files."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def isolated_env():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("GITLEAKS_", "GIT_CONFIG_")) or key in {
            "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_OBJECT_DIRECTORY",
            "GIT_EXEC_PATH", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
        }:
            env.pop(key, None)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_ATTR_NOSYSTEM": "1"})
    return env


def run(args, env, timeout=600):
    return subprocess.run(args, env=env, capture_output=True, text=True,
                          timeout=timeout, check=False)


def scan(binary, repository, config):
    env = isolated_env()
    binary, repository, config = [str(Path(p).resolve(strict=True))
                                  for p in (binary, repository, config)]
    version = run([binary, "version"], env, 20)
    if version.returncode or version.stdout.strip() != "8.30.1":
        raise RuntimeError("Unsupported scanner version; expected 8.30.1")
    shallow = run(["git", "-C", repository, "rev-parse", "--is-shallow-repository"], env, 20)
    if shallow.returncode or shallow.stdout.strip() != "false":
        raise RuntimeError("Repository unavailable or shallow; full reachable history is required")
    with tempfile.TemporaryDirectory(prefix="radar-secret-scan-") as task_dir:
        bare = str(Path(task_dir) / "repo.git")
        clone = run(["git", "-c", "core.hooksPath=" + os.devnull,
                     "clone", "--mirror", "--no-local", "--", repository, bare], env)
        if clone.returncode:
            raise RuntimeError("Failed to prepare history-only scan")
        # Bare clone has no working-tree .gitleaksignore. Explicit config is trusted base.
        report = str(Path(task_dir) / "raw-report.json")
        result = run([binary, "git", bare, "--config", config, "--redact=100",
                      "--ignore-gitleaks-allow", "--gitleaks-ignore-path", task_dir,
                      "--exit-code", "10", "--timeout", "540", "--no-banner",
                      "--no-color", "--log-level", "warn", "--report-format", "json",
                      "--report-path", report], env)
        if result.returncode not in (0, 10):
            # Never print captured upstream output: it may include untrusted metadata.
            raise RuntimeError("Scanner error or incomplete scan; check failed")
        findings = json.loads(Path(report).read_text())
        if not isinstance(findings, list):
            raise RuntimeError("Unexpected scanner report")
        if bool(findings) != (result.returncode == 10):
            raise RuntimeError("Scanner result/report mismatch")
        safe_findings = []
        for finding in findings:
            if finding.get("Secret") != "REDACTED":
                raise RuntimeError("Scanner report is not fully redacted for a finding")
            commit = finding.get("Commit", "")
            safe_findings.append({
                "rule": str(finding.get("RuleID", "unknown")),
                "commit": commit if re.fullmatch(r"[0-9a-f]{40,64}", commit) else "",
                "line": finding.get("StartLine") if isinstance(finding.get("StartLine"), int) else None,
            })
        # Commit messages, authors, emails, paths and raw matches are deliberately omitted.
        return {"scanner": "gitleaks", "version": "8.30.1", "mode": "full-reachable-git-history",
                "count": len(safe_findings), "findings": safe_findings}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    try:
        result = scan(args.binary, args.repository, args.config)
        Path(args.report).write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print("Secret scan failed to complete; no clean result is certified.")
        return 2
    print("Secret scan completed: " + str(result["count"]) + " candidate finding(s).")
    return 1 if result["count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
