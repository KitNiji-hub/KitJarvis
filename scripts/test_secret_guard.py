"""Offline regression checks in disposable repositories; never touches caller's index."""
import os
from pathlib import Path
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class SecretGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kitjarvis-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("scripts/secret_guard.py", ".gitleaks.toml", ".gitleaksignore", ".gitignore", ".githooks/pre-commit", ".githooks/pre-push"):
            dst = self.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, dst)
            if name.startswith(".githooks/"):
                dst.chmod(0o755)
        # Git passes repository environment to hooks; isolate our test repositories.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_AUTHOR_NAME="Guard Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Guard Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        self.git("init", "-q")
        self.git("config", "core.hooksPath", ".githooks")
        result = subprocess.run(["git", "config", "--local", "--get", "secretguard.gitleaksPath"], cwd=SOURCE, capture_output=True, text=True)
        exe = result.stdout.strip() or shutil.which("gitleaks")
        self.assertTrue(exe, "Install the scanner before running verification")
        self.git("config", "secretguard.gitleaksPath", exe)

    def run_cmd(self, args, data=None):
        return subprocess.run(args, cwd=self.root, env=self.env, input=data, capture_output=True, text=True)

    def git(self, *args, data=None):
        r = self.run_cmd(["git", *args], data)
        self.assertEqual(r.returncode, 0, "Temporary Git operation failed (output suppressed)")
        return r.stdout.strip()

    def stage(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", "-f", "--", name)

    def guard(self, mode, data=None):
        return self.run_cmd([sys.executable, "scripts/secret_guard.py", mode], data)

    def credential(self):
        return "gh" + "p_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(36))

    def commit_object(self, parent=None):
        tree = self.git("write-tree")
        args = ["commit-tree", tree, "-m", "Disposable secret-guard verification"]
        if parent:
            args += ["-p", parent]
        return self.git(*args)

    def test_clean_index_and_real_hook_pass(self):
        self.stage("ordinary.txt", "An ordinary clean change.\n")
        self.assertEqual(self.guard("staged").returncode, 0)
        self.assertEqual(self.run_cmd(["git", "hook", "run", "pre-commit"]).returncode, 0)

    def test_staged_secret_cannot_be_hidden_by_clean_worktree(self):
        token = self.credential()
        self.stage("candidate.txt", "token = " + token)
        (self.root / "candidate.txt").write_text("clean")
        r = self.run_cmd(["git", "hook", "run", "pre-commit"])
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(token, r.stdout + r.stderr)

    def test_forced_private_paths_block_and_example_passes(self):
        for name in (".env", "nested/.env.local", "private.key", ".aws/credentials", "config.json"):
            with self.subTest(name=name):
                self.stage(name, "placeholder")
                self.assertNotEqual(self.guard("staged").returncode, 0)
                self.git("rm", "--cached", "--", name)
        self.stage(".env.example", "OPENAI_API_KEY=REPLACE_ME\n")
        self.assertEqual(self.guard("staged").returncode, 0)

    def test_missing_scanner_blocks(self):
        self.git("config", "secretguard.gitleaksPath", str(self.root / "absent.exe"))
        self.assertNotEqual(self.guard("staged").returncode, 0)

    def test_push_checks_removed_secret_new_branch_and_multiple_refs(self):
        self.stage("ordinary.txt", "clean")
        clean = self.commit_object()
        token = self.credential()
        self.stage("candidate.txt", token)
        bad = self.commit_object(clean)
        self.git("rm", "--cached", "candidate.txt")
        tip = self.commit_object(bad)
        zeros = "0" * 40
        good_input = f"refs/heads/good {clean} refs/heads/good {zeros}\n"
        self.assertEqual(self.guard("pre-push", good_input).returncode, 0)
        bad_input = good_input + f"refs/heads/new {tip} refs/heads/new {zeros}\n"
        r = self.guard("pre-push", bad_input)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(token, r.stdout + r.stderr)
        self.env["SKIP_TESTS"] = "1"
        # Exercise the installed shell hook with Git's actual stdin contract.
        bash = shutil.which("bash")
        if os.name == "nt":
            candidate = Path(shutil.which("git")).resolve().parents[1] / "bin/bash.exe"
            if candidate.exists():
                bash = str(candidate)
        self.assertTrue(bash)
        r = self.run_cmd([bash, ".githooks/pre-push", "origin", "unused"], good_input)
        self.assertEqual(r.returncode, 0, "Clean pre-push hook should pass with only tests skipped")
        r = self.run_cmd([bash, ".githooks/pre-push", "origin", "unused"], bad_input)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Secret guard BLOCKED", r.stderr)
        self.assertNotIn(token, r.stdout + r.stderr)
        self.assertEqual(self.guard("pre-push", f"(delete) {zeros} refs/heads/good {clean}\n").returncode, 0)

    def test_inline_allow_comment_does_not_bypass(self):
        self.stage("candidate.txt", self.credential() + " # gitleaks:allow\n")
        self.assertNotEqual(self.guard("staged").returncode, 0)

    def test_example_contents_remain_scanned(self):
        self.stage("examples/config.json", '{"token": "' + self.credential() + '"}')
        self.assertNotEqual(self.guard("staged").returncode, 0)

    def test_private_key_and_password_are_blocked(self):
        header = "-----BEGIN " + "RSA PRIVATE KEY-----"
        footer = "-----END " + "RSA PRIVATE KEY-----"
        self.stage("ordinary.txt", header + "\n" + secrets.token_hex(64) + "\n" + footer)
        self.assertNotEqual(self.guard("staged").returncode, 0)
        # Gitleaks intentionally allows all-letter values and uses an entropy
        # threshold. Include every alphanumeric character exactly once so the
        # runtime-only fixture always contains digits and has high entropy.
        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.SystemRandom().sample(alphabet, len(alphabet)))
        self.stage("ordinary.txt", 'password = "' + password + '"')
        self.assertNotEqual(self.guard("staged").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
