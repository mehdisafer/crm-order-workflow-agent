"""Offline regression tests for the anonymous public-reachability validator."""

import importlib.util
import json
from pathlib import Path

import pytest


def load_public_checker():
    # The project packages crm_workflow from src/, not the repository's scripts/
    # directory. Load this exact script file rather than extending sys.path.
    source = Path(__file__).resolve().parents[1] / "scripts" / "check_public_access.py"
    spec = importlib.util.spec_from_file_location("public_access_checker", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load_public_checker()
RELEASE_SHA = checker.RELEASE_SHA
artifacts = checker.artifacts
validate_payload = checker.validate_payload


def test_all_public_resource_urls_are_expected_hosts():
    urls = artifacts("a" * 40)
    assert len(urls) == 9
    assert all(url.startswith("https://") for _, url in urls)
    assert not any("@" in url or "?token=" in url for _, url in urls)


def test_public_repository_identity_and_license_are_checked():
    good = {
        "full_name": "mehdisafer/crm-order-workflow-agent",
        "private": False,
        "default_branch": "main",
        "license": {"spdx_id": "Apache-2.0"},
    }
    validate_payload("repository", json.dumps(good).encode())
    for field, bad in [("private", True), ("default_branch", "other")]:
        with pytest.raises(ValueError):
            validate_payload("repository", json.dumps({**good, field: bad}).encode())


def test_release_cannot_be_silently_retargeted():
    valid = {"tag_name": "v0.1.0-rc.1", "target_commitish": RELEASE_SHA, "prerelease": True, "draft": False}
    validate_payload("release", json.dumps(valid).encode())
    with pytest.raises(ValueError):
        validate_payload("release", json.dumps({**valid, "target_commitish": "0" * 40}).encode())


def test_screenshot_needs_real_png_bytes_not_a_success_page():
    validate_payload("screenshot", b"\x89PNG\r\n\x1a\n" + b"x" * 4096)
    with pytest.raises(ValueError):
        validate_payload("screenshot", b"<html>please sign in</html>")


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("readme", b"# CRM Order Workflow Agent"),
        ("license", b"Apache License\nVersion 2.0"),
        ("source", b"from crm_workflow.models import Actor\ndef create_app(): pass"),
        ("landing", b"<html>crm-order-workflow-agent</html>"),
        ("release_page", b"<html>crm-order-workflow-agent v0.1.0-rc.1</html>"),
    ],
)
def test_expected_public_content_signatures(kind, payload):
    validate_payload(kind, payload)
