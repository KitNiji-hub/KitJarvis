"""Local, fail-closed Gitleaks runner. Requires Python 3.11+ and Gitleaks 8.30.1."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = "8.30.1"
ROOT = Path(__file__).resolve().parents[1]
SAFE_ENV = {".env.example", ".env.sample", ".env.template"}
PRIVATE_NAMES = {
    ".envrc", ".netrc", "_netrc", ".npmrc", ".pypirc", "config.json",
    "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml",
    "secrets.toml", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    ".git-credentials", ".dockercfg", ".secrets", ".credentials",
    "application_default_credentials.json", "token.json", "tokens.json",
}
PRIVATE_GLOBS = (
    "config.json.backup-*", "credentials.*.json", "client_secret*.json",
    "service-account*.json", "*.pem", "*.key", "*.p12", "*.pfx",
    "*.jks", "*.keystore", "*.tfstate", "*.tfstate.*", "*.tfvars", "*.tfvars.json",
    "*.env", "*.kdbx",
)


class GuardError(Exception):
    pass


def git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if result.returncode or b"permission denied" in result.stderr.lower():
        # Git errors can contain content, URLs or credential-bearing arguments.
        raise GuardError("Git operation failed or encountered an unreadable path; raw diagnostics suppressed.")
    return result.stdout


def private_path(name: str) -> bool:
    # Existing intentional example; content is still scanned without exclusions.
    if name == "examples/config.json":
        return False
    parts = PurePosixPath(name.lower()).parts
    return any(
        p in PRIVATE_NAMES or p in {".aws", ".azure", ".ssh", ".kube"}
        or ((p == ".env" or p.startswith(".env.")) and p not in SAFE_ENV)
        or any(fnmatch.fnmatchcase(p, pattern) for pattern in PRIVATE_GLOBS)
        for p in parts
    )


def check_paths(names: list[str]) -> None:
    blocked = sorted({p for p in names if private_path(p)})
    if blocked:
        for p in blocked:
            print("Blocked credential/config path:", json.dumps(p))
        raise GuardError("Private files must stay outside Git, even when force-added.")


def scanner() -> str:
    # A per-checkout path avoids changing global PATH or installing app dependencies.
    configured = git("config", "--local", "--get", "secretguard.gitleaksPath") if has_setting() else b""
    exe = configured.decode().strip() or shutil.which("gitleaks")
    if not exe:
        raise GuardError("Gitleaks missing. Run scripts/install_secret_hooks.ps1 -GitleaksPath <path>.")
    result = subprocess.run([exe, "version"], capture_output=True, text=True)
    if result.returncode or result.stdout.strip().removeprefix("v") != VERSION:
        raise GuardError(f"Gitleaks {VERSION} is required; install the pinned version.")
    return exe


def has_setting() -> bool:
    return subprocess.run(
        ["git", "config", "--local", "--get", "secretguard.gitleaksPath"],
        cwd=ROOT, capture_output=True,
    ).returncode == 0


def scan(exe: str, mode: str, target: Path, *args: str) -> None:
    with tempfile.TemporaryDirectory(prefix="kitjarvis-gitleaks-") as tmp:
        report = Path(tmp) / "report.json"
        result = subprocess.run([
            exe, mode, str(target), "--config", str(ROOT / ".gitleaks.toml"),
            "--gitleaks-ignore-path", str(ROOT / ".gitleaksignore"),
            "--ignore-gitleaks-allow", "--redact=100", "--no-banner", "--no-color",
            "--report-format", "json", "--report-path", str(report), *args,
        ], cwd=ROOT, capture_output=True)
        # Only metadata leaves the scanner. Do not echo Match, Secret or raw stderr.
        findings = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
        if findings:
            for f in findings:
                print(json.dumps({k: f.get(k) for k in ("RuleID", "File", "StartLine", "Commit")}))
        diagnostics = result.stderr.lower()
        if result.returncode or findings or findings is None or b"skipping" in diagnostics or b"error" in diagnostics:
            raise GuardError("Scan blocked: potential secret or incomplete scan. Values are redacted.")


def snapshot(exe: str, staged: bool, changed_only: bool = False) -> None:
    entries = git("ls-files", "--stage", "-z").split(b"\0")
    names = []
    blobs = []
    for entry in filter(None, entries):
        meta, raw = entry.split(b"\t", 1)
        mode, oid, stage = meta.decode().split()
        name = raw.decode("utf-8")
        if stage != "0":
            raise GuardError("Resolve the unmerged index before scanning.")
        if mode == "160000":
            raise GuardError("Submodules require an independent secret audit; scan cannot certify them.")
        names.append(name)
        blobs.append((name, oid))
    if not staged:
        names += [n.decode("utf-8") for n in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if n]
    check_paths(names)
    if changed_only:
        changed = {p.decode("utf-8") for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0") if p}
        blobs = [(name, oid) for name, oid in blobs if name in changed]
    with tempfile.TemporaryDirectory(prefix="kitjarvis-secret-snapshot-") as tmp:
        dest = Path(tmp)
        if staged:
            # Read blobs, never the worktree: unstaged edits cannot hide staged secrets.
            for name, oid in blobs:
                p = dest / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(git("cat-file", "blob", oid))
        else:
            for name in set(names):
                src = ROOT / name
                if src.is_symlink():
                    data = os.readlink(src).encode()
                elif src.exists():
                    data = src.read_bytes()
                else:
                    continue  # deleted worktree file; index is checked separately
                p = dest / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
        scan(exe, "dir", dest)


def history(exe: str, refs: list[str]) -> None:
    if git("rev-parse", "--is-shallow-repository").strip() == b"true":
        raise GuardError("Full history required. Obtain it before retrying; guard never fetches.")
    # Scan every ancestor, including merge diffs, removed secrets and new branches/tags.
    opts = ["--full-history", "--root", "-m", *refs]
    paths = git("log", *opts, "--format=", "--name-only", "-z", "--diff-filter=ACMR")
    check_paths([p.decode("utf-8").strip("\n") for p in paths.split(b"\0") if p.strip()])
    scan(exe, "git", ROOT, "--log-opts=" + " ".join(opts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["staged", "tracked", "worktree", "history", "pre-push", "check"])
    args = parser.parse_args()
    try:
        exe = scanner()
        if args.mode == "staged":
            snapshot(exe, True, changed_only=True)
        elif args.mode == "tracked":
            snapshot(exe, True)
        elif args.mode == "worktree":
            snapshot(exe, False)
        elif args.mode == "history":
            history(exe, ["--all"])
        elif args.mode == "pre-push":
            refs = []
            for line in sys.stdin:
                fields = line.split()
                if len(fields) != 4 or not all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", fields[i]) for i in (1, 3)):
                    raise GuardError("Malformed pre-push ref input.")
                oid = fields[1]
                if set(oid) != {"0"}:
                    # Peel annotated tags; non-commit refs fail closed.
                    refs.append(git("rev-parse", "--verify", oid + "^{commit}").decode().strip())
            if refs:
                history(exe, sorted(set(refs)))
        print(f"Secret guard: {args.mode} passed (Gitleaks {VERSION}).")
        return 0
    except GuardError as exc:
        print(f"Secret guard BLOCKED: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Secret guard BLOCKED. Check the metadata above, scanner installation, and SECURITY.md.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
