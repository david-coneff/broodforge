#!/usr/bin/env python3
"""CLI entry point for the Talos machine config generator (9.T.3)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from generate_talos_config import main

sys.exit(main())
