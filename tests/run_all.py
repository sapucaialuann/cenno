"""Run every test in this folder.  Usage:

    python tests/run_all.py
"""

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def main():
    failed = []
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        name = os.path.basename(path)
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        result = subprocess.run([PYTHON, path])
        if result.returncode:
            failed.append(name)
    print()
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
