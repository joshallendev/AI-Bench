#!/usr/bin/env python3
"""Compatibility wrapper for the AI-Bench CLI."""

import sys

from ai_bench import cli as _cli


if __name__ == "__main__":
    raise SystemExit(_cli.cli_main())

sys.modules[__name__] = _cli
