"""Shared test setup."""
import os

# the update reminder never reaches the network from the tests (tests/test_update.py turns it on for its own origin)
os.environ.setdefault("SLOP_UPDATE_CHECK", "0")
# the home-GPU link is parked in the shipped bot (SLOP_GPU unset); its tests keep running with it switched on
os.environ.setdefault("SLOP_GPU", "1")
