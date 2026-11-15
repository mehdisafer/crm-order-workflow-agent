"""Verify the selected project licence is reflected in packaging metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_apache_license_metadata_and_standard_text():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    licence = (root / "LICENSE").read_text(encoding="utf-8")

    assert metadata["version"] == "0.1.0rc1"
    assert metadata["license"] == "Apache-2.0"
    assert "LICENSE" in metadata["license-files"]
    assert licence.startswith("Apache License\nVersion 2.0, January 2004")
    assert "END OF TERMS AND CONDITIONS" in licence
    assert "APPENDIX: How to apply the Apache License to your work" in licence
