"""
Compatibility CLI entry point for RSS-Syphon.

The application implementation lives in the rss_syphon package; this wrapper
preserves the existing `python src/rss_syphon.py` invocation.
"""

import sys

from rss_syphon.cli import main


if __name__ == "__main__":
    sys.exit(main())
