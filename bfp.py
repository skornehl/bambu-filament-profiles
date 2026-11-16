#!/usr/bin/env python3
"""Run the tool straight from the checked-out repo, without installing it.

Example:  python bfp.py install --vendor SUNLU --material PLA --dry-run
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bambu_filament_profiles.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
