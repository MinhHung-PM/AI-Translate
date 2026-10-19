"""Operational commands: ``python -m app.cli <command>``.

* ``seed``           — load development seed data
* ``generate-key``   — print a new kid:base64 entry for SECRET_ENCRYPTION_KEYS
* ``rotate-keys``    — re-encrypt stored API keys with the primary key
* ``retention``      — enforce data retention now
* ``make-admin EMAIL`` — give an existing user (signed in once) the admin role
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
            from app.core.config import get_settings
            from app.seed import seed

            seed(db)  # prints and skips in production
            if not get_settings().is_production:
                print("Seed data loaded")
        elif cmd == "rotate-keys":
            from app.services.provider_config import rotate_persistent_keys

            n = rotate_persistent_keys(db)
            db.commit()
            print(f"Re-encrypted {n} secrets")
        elif cmd == "make-admin":
            from sqlalchemy import select

            from app.models import User
            from app.models.enums import GlobalRole

            email = (argv[1] if len(argv) > 1 else "").strip().lower()
            user = db.scalar(select(User).where(User.email == email)) if email else None
            if user is None:
                print("No user with that e-mail. Sign in once with that account, then run this again.")
                return 1
            user.role = GlobalRole.admin
            db.commit()
            print(f"{email} is now an admin")
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
