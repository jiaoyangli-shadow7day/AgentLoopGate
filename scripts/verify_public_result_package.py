#!/usr/bin/env python3
"""Verify a sanitized public package without private experiment data."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("verify_public_r2_package.py")),
        run_name="__main__",
    )
