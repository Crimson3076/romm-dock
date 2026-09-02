"""``python -m atlas`` — the CLI without the console script installed."""

import sys

from _vendor.atlas.cli import main

if __name__ == "__main__":
    sys.exit(main())
