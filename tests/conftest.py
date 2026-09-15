"""Test files import each other's fixtures (BANK, SSN) and the app under
test. `pytest` from the repo root and `python -m pytest` from anywhere
put different directories on sys.path; pin both so every invocation
resolves the same modules."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "tests"), os.path.join(ROOT, "webapp")):
    if path not in sys.path:
        sys.path.insert(0, path)
