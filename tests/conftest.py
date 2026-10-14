"""Shared test setup."""
import os

# the update reminder never reaches the network from the tests (tests/test_update.py turns it on for its own origin)
os.environ.setdefault("SLOP_UPDATE_CHECK", "0")
