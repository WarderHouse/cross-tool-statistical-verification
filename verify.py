#!/usr/bin/env python3
"""Convenience entrypoint: `python verify.py --project examples/project.yaml`
(identical to `python -m crossverify`)."""
import sys

from crossverify.cli import main

if __name__ == "__main__":
    sys.exit(main())
