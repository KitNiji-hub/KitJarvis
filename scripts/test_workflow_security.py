"""Static security checks for GitHub workflow and ownership configuration."""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
USES = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    workflow_paths = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    if not workflow_paths:
        fail("No GitHub workflows found")

    external_uses = 0
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8-sig")
        if re.search(r"^\s*pull_request_target\s*:", text, re.MULTILINE):
            fail(f"{path.name}: pull_request_target is forbidden")
        if not re.search(
            r"^permissions:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+contents:\s*read\s*(?:#.*)?$",
            text,
            re.MULTILINE,
        ):
            fail(f"{path.name}: missing top-level contents: read permission")
        for use in USES.findall(text):
            if use.startswith("./"):
                continue
            external_uses += 1
            if not FULL_SHA.fullmatch(use):
                fail(f"{path.name}: external action is not pinned to a full SHA: {use}")

    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    for protected in ("/.github/", "/.githooks/", "/.gitleaks.toml", "/.gitleaksignore"):
        if not re.search(rf"^{re.escape(protected)}\s+@KitNiji-hub\s*$", owners, re.MULTILINE):
            fail(f"CODEOWNERS does not protect {protected}")

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    for ecosystem in ("pip", "github-actions"):
        if f"package-ecosystem: {ecosystem}" not in dependabot:
            fail(f"Dependabot does not cover {ecosystem}")

    print(
        f"Workflow security passed: {len(workflow_paths)} workflows, "
        f"{external_uses} SHA-pinned external actions."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError) as exc:
        print(f"Workflow security BLOCKED: {exc}", file=sys.stderr)
        sys.exit(1)
