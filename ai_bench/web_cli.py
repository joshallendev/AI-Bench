#!/usr/bin/env python3
"""AI-Bench Web Controller - thin executable entry point."""

import argparse
import os
import sys
from pathlib import Path

from ai_bench import package_static_dir


def build_arg_parser() -> argparse.ArgumentParser:
    """Return the CLI parser for the web controller."""
    parser = argparse.ArgumentParser(
        description="AI-Bench Web Controller",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1). "
        "Only loopback unless --allow-non-loopback is passed.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Run workspace root (default: current directory).",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="Results directory (default: ~/ai-bench/results or $AGENT_BENCH_RESULTS_DIR).",
    )
    parser.add_argument(
        "--python",
        type=str,
        default=None,
        help="Python executable to run ai_bench.cli (default: sys.executable).",
    )
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="Allow binding to non-loopback addresses.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Start the localhost web controller."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    root = (args.root or Path.cwd()).resolve()
    results_dir = args.results_dir or Path(
        os.environ.get("AGENT_BENCH_RESULTS_DIR") or str(Path.home() / "ai-bench" / "results")
    )
    python_executable = Path(args.python or sys.executable)

    from ai_bench.web_server import (
        WebServerConfig,
        serve,
        validate_server_config,
    )

    config = WebServerConfig(
        host=args.host,
        port=args.port,
        root=root,
        static_root=package_static_dir(),
        results_dir=results_dir,
        python_executable=python_executable,
        allow_non_loopback=args.allow_non_loopback,
    )

    try:
        validate_server_config(config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    serve(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
