"""Synthetic-only CLI and original Radar wrapper checks; no provider requests."""
import json
import os
from pathlib import Path
import random
import string
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get("RADAR_GITLEAKS_BINARY", "/tmp/radar-gitleaks/gitleaks"))
WRAPPER = ROOT / "scripts/scan_secrets.py"
TRUSTED = ROOT / ".security/gitleaks.toml"
TOKEN = "gh" + "p_" + "".join(random.Random(481516).choices(string.ascii_letters + string.digits, k=36))


class OfflineChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="radar-gitleaks-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(("GITLEAKS_", "GIT_CONFIG_")):
                self.env.pop(key, None)
        self.env["GIT_CONFIG_GLOBAL"] = os.devnull
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"

    def run_cli(self, mode, path, **options):
        report = self.root / (options.pop("name", "report") + ".json")
        args = [str(BINARY), mode, str(path), "--redact=100", "--no-banner", "--no-color",
                "--report-format", "json", "--report-path", str(report), "--timeout", "30"]
        args.extend(options.pop("extra", []))
        result = subprocess.run(args, capture_output=True, text=True, env=self.env,
                                timeout=40, check=False)
        findings = json.loads(report.read_text()) if report.exists() else None
        return result, findings

    def repo(self):
        repo = self.root / "repo"
        repo.mkdir()
        self.git(repo, "init", "--initial-branch=main")
        self.git(repo, "config", "user.name", "Synthetic Fixture")
        self.git(repo, "config", "user.email", "fixture@example.invalid")
        return repo

    def git(self, repo, *args):
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                text=True, env=self.env, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, "Git fixture setup failed")
        return result

    def commit(self, repo, message="synthetic fixture"):
        self.git(repo, "add", "--all")
        self.git(repo, "commit", "--quiet", "-m", message)

    def run_wrapper(self, repo, config=TRUSTED):
        report = self.root / "summary.json"
        result = subprocess.run(["python3", str(WRAPPER), "--binary", str(BINARY),
                                 "--repository", str(repo), "--config", str(config),
                                 "--report", str(report)], env=self.env,
                                capture_output=True, text=True, timeout=60, check=False)
        return result, json.loads(report.read_text()) if report.exists() else None

    def test_clean_directory_exits_zero(self):
        directory = self.root / "clean"
        directory.mkdir()
        (directory / "note.txt").write_text("ordinary synthetic content\n")
        result, findings = self.run_cli("dir", directory)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(findings, [])

    def test_secret_exits_one_and_primary_json_is_redacted(self):
        directory = self.root / "secret"
        directory.mkdir()
        (directory / "sample.txt").write_text("token=" + TOKEN + "\n")
        result, findings = self.run_cli("dir", directory)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(findings)
        self.assertTrue(all(f["Secret"] == "REDACTED" for f in findings))
        self.assertNotIn(TOKEN, json.dumps(findings) + result.stdout + result.stderr)

    def test_malformed_config_is_nonzero_and_not_clean(self):
        directory = self.root / "invalid"
        directory.mkdir()
        config = self.root / "invalid.toml"
        config.write_text("[[rules]\ninvalid TOML")
        result, _ = self.run_cli("dir", directory, extra=["--config", str(config)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unable to load", result.stderr)

    def test_removed_secret_is_found_in_history_but_not_current_files(self):
        repo = self.repo()
        (repo / "sample.txt").write_text("token=" + TOKEN + "\n")
        self.commit(repo)
        (repo / "sample.txt").write_text("ordinary synthetic content\n")
        self.commit(repo, "remove synthetic marker")
        current, current_findings = self.run_cli("dir", repo, name="current")
        history, history_findings = self.run_cli("git", repo, name="history")
        self.assertEqual(current.returncode, 0)
        self.assertEqual(current_findings, [])
        self.assertEqual(history.returncode, 1)
        self.assertTrue(history_findings)
        self.assertNotIn(TOKEN, json.dumps(history_findings) + history.stdout + history.stderr)

    def test_multipart_verbose_redaction_gap_is_reproduced(self):
        # This passing audit test confirms a defect; it is not a safety certification.
        directory = self.root / "multipart"
        directory.mkdir()
        primary = "primary_fixture_value"
        auxiliary = "auxiliary_fixture_value"
        (directory / "sample.txt").write_text('password="' + primary + '"\nusername="' + auxiliary + '"\n')
        config = self.root / "multipart.toml"
        config.write_text('''title = "Synthetic multipart audit"
[[rules]]
id = "primary"
regex = 'password="([^"]+)"'
secretGroup = 1
[[rules.required]]
id = "auxiliary"
withinLines = 1
[[rules]]
id = "auxiliary"
regex = 'username="([^"]+)"'
secretGroup = 1
skipReport = true
''')
        result, findings = self.run_cli("dir", directory, extra=["--config", str(config), "--verbose"])
        self.assertEqual(result.returncode, 1)
        self.assertTrue(findings)
        self.assertNotIn(primary, json.dumps(findings) + result.stdout)
        self.assertIn(auxiliary, result.stdout)
        self.assertNotIn(auxiliary, json.dumps(findings))

    def test_wrapper_clean_repository(self):
        repo = self.repo()
        (repo / "note.txt").write_text("ordinary synthetic content\n")
        self.commit(repo)
        result, report = self.run_wrapper(repo)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["count"], 0)

    def test_wrapper_ignores_pr_policy_downgrade_and_omits_commit_metadata(self):
        repo = self.repo()
        (repo / "sample.txt").write_text("token=" + TOKEN + " # gitleaks:allow\n")
        (repo / ".gitleaks.toml").write_text('[[rules]]\nid="no-match"\nregex="^NEVER_MATCH_RADAR_FIXTURE$"\n')
        (repo / ".gitleaksignore").write_text("sample.txt:github-pat:1\n")
        self.commit(repo, "synthetic commit message " + TOKEN)
        direct, findings = self.run_cli("git", repo)
        self.assertEqual(direct.returncode, 0)
        self.assertEqual(findings, [])
        result, report = self.run_wrapper(repo)
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(report["count"], 1)
        self.assertNotIn(TOKEN, json.dumps(report) + result.stdout + result.stderr)
        self.assertTrue(all(set(f) == {"rule", "commit", "line"} for f in report["findings"]))

    def test_wrapper_invalid_trusted_policy_exits_two(self):
        repo = self.repo()
        (repo / "note.txt").write_text("ordinary synthetic content\n")
        self.commit(repo)
        policy = self.root / "invalid.toml"
        policy.write_text("[[rules]\ninvalid TOML")
        result, report = self.run_wrapper(repo, policy)
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report)

    def test_wrapper_mirror_preserves_remote_ref_only_history(self):
        repo = self.repo()
        (repo / "note.txt").write_text("ordinary synthetic content\n")
        self.commit(repo)
        self.git(repo, "checkout", "-b", "temporary-topic")
        (repo / "sample.txt").write_text("token=" + TOKEN + "\n")
        self.commit(repo)
        self.git(repo, "update-ref", "refs/remotes/upstream/topic", "HEAD")
        self.git(repo, "checkout", "main")
        self.git(repo, "branch", "-D", "temporary-topic")
        # The secret commit is reachable only through a remote-tracking ref.
        result, report = self.run_wrapper(repo)
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(report["count"], 1)
        self.assertNotIn(TOKEN, json.dumps(report) + result.stdout + result.stderr)

    def test_wrapper_refuses_shallow_history(self):
        repo = self.repo()
        (repo / "note.txt").write_text("ordinary synthetic content\n")
        self.commit(repo)
        shallow = self.root / "shallow"
        result = subprocess.run(["git", "clone", "--depth", "1", repo.as_uri(), str(shallow)],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        result, report = self.run_wrapper(shallow)
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report)

    def test_cli_timeout_of_controlled_git_subprocess_is_error_not_clean(self):
        # Controlled local Git shim blocks its log call. This verifies the real CLI's
        # timeout handling, not real-repository performance or full timeout coverage.
        directory = self.root / "timeout-source"
        directory.mkdir()
        shim_dir = self.root / "shim-bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text('#!/usr/bin/env python3\nimport sys, time\nif "log" in sys.argv:\n    time.sleep(3)\n')
        shim.chmod(0o700)
        self.env["PATH"] = str(shim_dir) + os.pathsep + self.env["PATH"]
        result, findings = self.run_cli("git", directory,
                                       extra=["--timeout", "1", "--exit-code", "10"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("partial scan", result.stderr)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
