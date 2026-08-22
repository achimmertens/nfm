"""Main application package."""

import tomllib
from pathlib import Path

with open(Path(__file__).resolve().parent.parent / "pyproject.toml", "rb") as _f:
    __version__ = tomllib.load(_f)["project"]["version"]
