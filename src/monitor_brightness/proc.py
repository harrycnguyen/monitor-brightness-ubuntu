"""Thin subprocess wrapper so backends can be tested without real tools."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


def run(cmd: list[str], timeout: float = 15.0) -> Result:
    """Run a command. Raises FileNotFoundError if the binary is missing."""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return Result(p.returncode, p.stdout, p.stderr)
