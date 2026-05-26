#!/usr/bin/env python3
"""Compatibility wrapper for the AI-Bench web controller."""

import sys

from ai_bench.web_cli import main


if __name__ == "__main__":
    sys.exit(main())
