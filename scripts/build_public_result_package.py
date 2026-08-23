#!/usr/bin/env python3
"""Build a fail-closed public package for a verified formal experiment.

The implementation remains in the historical compatibility module while its
inputs are derived from the supplied freeze manifest and formal configuration.
"""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("build_public_r2_package.py")),
        run_name="__main__",
    )
