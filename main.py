"""Backward-compatible source-tree entry point.

Use the installed ``regulatory-ingest`` command for normal execution.
"""

from regulatory_ingest.cli import main


if __name__ == "__main__":
    main()
