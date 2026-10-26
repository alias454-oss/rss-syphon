"""
Allow running RSS-Syphon as a Python module.

Equivalent to invoking the existing src/rss_syphon.py entry point.
"""

import sys

from .cli import main


if __name__ == "__main__":
    sys.exit(main())
