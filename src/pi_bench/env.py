"""Environment variable loading for pi-bench entrypoints."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None = None) -> None:
    """Load simple KEY=VALUE entries from a .env file if present.

    Existing process environment variables win. This intentionally supports the
    small subset we need for API keys and model defaults without adding a
    runtime dependency.
    """
    for env_path in _candidate_paths(path):
        _load_file(env_path)


def _candidate_paths(path: str | Path | None) -> list[Path]:
    if path is not None:
        return [Path(path)]

    workspace = Path(__file__).resolve().parents[2] / ".env"
    cwd = Path.cwd() / ".env"
    paths = [workspace]
    if cwd != workspace:
        paths.append(cwd)
    return paths


def _load_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _strip_quotes(value.strip())
        os.environ.setdefault(key, value)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
