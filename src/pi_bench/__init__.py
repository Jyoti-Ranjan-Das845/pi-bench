"""pi-bench public package metadata."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("pi-bench")
except PackageNotFoundError:
    # Source-tree fallback for local development without an installed dist-info.
    __version__ = "0.1.0"


__all__ = ["__version__"]
