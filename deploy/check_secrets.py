"""Focused credential scan of tracked/worktree text and every reachable Git blob.

This is a deterministic review aid, not an assurance certificate or replacement
for provider secret scanning. Finding output never includes a matching secret.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "aws-access-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    "literal-credential": re.compile(
        rb"(?i)[\"']?(?:password|secret|api_key|access_token|refresh_token)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9+/_=-]{24,}[\"']"
    ),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def inspect(content: bytes, identity: str) -> list[dict]:
    if b"\x00" in content[:8192]:
        return []
    return [
        {"source": identity, "rule": name, "line": content[: match.start()].count(b"\n") + 1}
        for name, pattern in PATTERNS.items()
        for match in pattern.finditer(content)
    ]


def main() -> None:
    findings: list[dict] = []
    paths = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")))
    for raw_path in paths:
        if not raw_path:
            continue
        name = raw_path.decode()
        path = ROOT / name
        if not path.is_file():
            continue
        if (
            name.startswith((".local/", "deploy/secrets/"))
            or path.name in {"principals.json", "tokens.json", ".env"}
            or path.suffix in {".pem", ".key", ".pfx"}
        ):
            findings.append({"source": name, "rule": "private-file-in-source"})
        findings.extend(inspect(path.read_bytes(), name))
    history_blobs = 0
    has_history = (
        subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True, check=False
        ).returncode
        == 0
    )
    if has_history:
        # --batch-check classifies objects without printing their content.
        objects = git("rev-list", "--objects", "--all").splitlines()
        identifiers = [entry.split(b" ", 1)[0] for entry in objects]
        classified = subprocess.check_output(
            ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
            cwd=ROOT,
            input=b"\n".join(identifiers) + b"\n",
        )
        for row in classified.splitlines():
            oid, kind = row.split()
            if kind == b"blob":
                history_blobs += 1
                findings.extend(inspect(git("cat-file", "blob", oid.decode()), f"git:{oid.decode()}"))
    print(
        json.dumps(
            {"worktree_files": len(paths) - 1, "history_blobs": history_blobs, "findings": findings}, indent=2
        )
    )
    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    main()
