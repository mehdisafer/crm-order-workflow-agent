"""Check this project's published resources using anonymous HTTPS requests only.

This is an availability check, not a browser rendering audit, security audit or
Salesforce/MuleSoft provider acceptance. No GitHub token, cookie or user session
is attached to any request. The exact source commit and historical release tag
are verified independently, without reassigning the release to newer code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

REPOSITORY = "mehdisafer/crm-order-workflow-agent"
RELEASE_TAG = "v0.1.0-rc.1"
RELEASE_SHA = "cdf3c0ec523db4a0916eac1e885a14084d882f59"
MAX_CONTENT_BYTES = 4 * 1024 * 1024
USER_AGENT = "crm-order-workflow-agent-anonymous-access-audit/1.0"


def validate_payload(kind: str, content: bytes) -> None:
    """Fail closed when an HTTP 200 response is an unrelated page."""
    if kind == "repository":
        data = json.loads(content)
        if not (
            data.get("full_name") == REPOSITORY
            and data.get("private") is False
            and data.get("default_branch") == "main"
            and (data.get("license") or {}).get("spdx_id") == "Apache-2.0"
        ):
            raise ValueError("Public repository identity/licence mismatch")
    elif kind == "release":
        data = json.loads(content)
        if not (
            data.get("tag_name") == RELEASE_TAG
            and data.get("target_commitish") == RELEASE_SHA
            and data.get("prerelease") is True
            and data.get("draft") is False
        ):
            raise ValueError("Published release identity or original target mismatch")
    elif kind == "readme":
        if b"# CRM Order Workflow Agent" not in content:
            raise ValueError("Public README is not the expected project")
    elif kind == "license":
        if not content.startswith(b"Apache License\nVersion 2.0") and not content.startswith(
            b"Apache License\r\nVersion 2.0"
        ):
            raise ValueError("Apache-2.0 licence text not found")
    elif kind == "source":
        if b"def create_app(" not in content or b"crm_workflow" not in content:
            raise ValueError("Public Python source does not contain expected API")
    elif kind == "screenshot":
        if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) < 4096:
            raise ValueError("Public screenshot is not a substantial PNG")
    elif kind in {"landing", "screenshot_page", "release_page"}:
        if b"crm-order-workflow-agent" not in content:
            raise ValueError("Public GitHub page is not the expected repository")
        if kind == "release_page" and RELEASE_TAG.encode() not in content:
            raise ValueError("Public GitHub release page does not show the expected tag")
    else:
        raise ValueError("Unknown public artifact kind")


def read_anonymously(url: str) -> tuple[bytes, str]:
    """Never inherit auth cookies, repository tokens or environment proxy credentials."""
    if urlsplit(url).scheme != "https":
        raise ValueError("Non-HTTPS resource prohibited")
    host = urlsplit(url).hostname
    if host not in {"github.com", "api.github.com", "raw.githubusercontent.com"}:
        raise ValueError("Unexpected host")
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        method="GET",
    )
    if any(key.lower() in {"authorization", "cookie"} for key in request.headers):
        raise ValueError("Authenticated request prohibited")
    # No cookie handler and no inherited authenticated proxy configuration.
    opener = build_opener(ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(request, timeout=20) as response:
                final_url = response.geturl()
                if urlsplit(final_url).hostname != host or urlsplit(final_url).path.startswith("/login"):
                    raise ValueError("Public URL redirected to a different host or login")
                content = response.read(MAX_CONTENT_BYTES + 1)
                if len(content) > MAX_CONTENT_BYTES:
                    raise ValueError("Public resource exceeds the configured size ceiling")
                return content, final_url
        except HTTPError as exc:
            if attempt == 2 or exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except (TimeoutError, URLError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    raise RuntimeError("Public availability retries exhausted")


def artifacts(source_sha: str) -> list[tuple[str, str]]:
    root = f"https://raw.githubusercontent.com/{REPOSITORY}/{source_sha}"
    github = f"https://github.com/{REPOSITORY}"
    return [
        ("repository", f"https://api.github.com/repos/{REPOSITORY}"),
        ("landing", github),
        ("readme", f"{root}/README.md"),
        ("license", f"{root}/LICENSE"),
        ("source", f"{root}/src/crm_workflow/api.py"),
        (
            "screenshot",
            f"{root}/docs/evidence/firefox-ui/final-run/operator-desktop-detail.png",
        ),
        (
            "screenshot_page",
            f"{github}/blob/{source_sha}/docs/evidence/firefox-ui/final-run/operator-desktop-detail.png",
        ),
        ("release", f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{RELEASE_TAG}"),
        ("release_page", f"{github}/releases/tag/{RELEASE_TAG}"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="Current main source commit (40 hex characters)")
    parser.add_argument("--output", default="evidence-local/public-access.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        raise SystemExit("An exact lowercase 40-character Git SHA is required")
    result = {
        "check": "public_unauthenticated_http_artifacts",
        "status": "failed",
        "observed_at": datetime.now(UTC).isoformat(),
        "source_sha": args.sha,
        "release_sha": RELEASE_SHA,
        "auth": "none (no cookies, tokens or inherited proxy credentials)",
        "scope": "Public HTTP availability and source identity; not rendered browser UX or vendor acceptance",
        "resources": [],
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        for kind, url in artifacts(args.sha):
            content, final_url = read_anonymously(url)
            validate_payload(kind, content)
            result["resources"].append(
                {
                    "kind": kind,
                    "url": url,
                    "final_url": final_url,
                    "status": "passed",
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        result["status"] = "passed"
    except Exception as exc:
        # Never write the HTTP response body, remote exception text or any secret.
        result["failure_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            result["http_status"] = exc.code
        raise
    finally:
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "resources": len(result["resources"])}))


if __name__ == "__main__":
    main()
