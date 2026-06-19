"""Version single-source-of-truth: pyproject.toml is authoritative; the plugin
manifest must stay in sync, and the importable __version__ must match it when the
package is installed. These guard against the three drifting apart on a release."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import portfolio

_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    with open(_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def _plugin_version() -> str:
    data = json.loads((_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return data["version"]


def test_plugin_version_matches_pyproject():
    """The Claude Code plugin manifest version must equal pyproject's version."""
    assert _plugin_version() == _pyproject_version()


def test_package_version_matches_pyproject_when_installed():
    """When installed (editable or wheel), portfolio.__version__ equals pyproject's
    version. Skipped only if the package isn't installed (raw checkout)."""
    if portfolio.__version__ == "0.0.0+unknown":
        import pytest

        pytest.skip("portfolio is not installed; __version__ falls back")
    assert portfolio.__version__ == _pyproject_version()
