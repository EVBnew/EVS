# tools/hash_password.py
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.access import hash_password  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/hash_password.py <plain_password>")
        return 2
    pwd = sys.argv[1]
    print(hash_password(pwd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
