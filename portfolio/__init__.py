"""portfolio: turn a developer's real git/GitHub work into a grounded
portfolio — every claim traced to evidence, never invented."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth is pyproject's [project].version; when the package
    # is installed (incl. `pip install -e .`) this reads that exact value.
    __version__ = version("portfolio")
except PackageNotFoundError:  # running from a raw checkout without an install
    __version__ = "0.0.0+unknown"
