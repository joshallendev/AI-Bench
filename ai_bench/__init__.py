from pathlib import Path


def package_static_dir() -> Path:
    """Return the directory containing packaged web assets."""
    return Path(__file__).with_name("static")
