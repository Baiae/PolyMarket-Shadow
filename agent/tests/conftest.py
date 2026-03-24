"""
conftest.py — pytest configuration for the Poly-Shadow agent test suite.

Adds agent/src/ to sys.path so tests can import config, risk, strategy etc.
directly without needing a package install step.
"""
import sys
import os

# Ensure agent/src is on the path regardless of where pytest is invoked from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
