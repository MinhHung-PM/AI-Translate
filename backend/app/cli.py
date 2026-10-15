"""Operational commands: ``python -m app.cli <command>``.

* ``seed``           — load development seed data
* ``generate-key``   — print a new kid:base64 entry for SECRET_ENCRYPTION_KEYS
* ``rotate-keys``    — re-encrypt stored API keys with the primary key
* ``retention``      — enforce data retention now
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from app.core.crypto import generate_key
from app.db.session import get_sessionmaker


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "generate-key":
        print(f"k{datetime.now(UTC):%Y%m%d}:{generate_key()}")
        return 0
    with get_sessionmaker()() as db:
        if cmd == "seed":
            from app.seed import seed

            seed(db)
            print("Seed data loaded")
        elif cmd == "rotate-keys":
            from app.services.provider_config import rotate_persistent_keys

            n = rotate_persistent_keys(db)
            db.commit()
            print(f"Re-encrypted {n} secrets")
        elif cmd == "retention":
            from app.services.retention import enforce_retention

            print(enforce_retention(db))
            db.commit()
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
