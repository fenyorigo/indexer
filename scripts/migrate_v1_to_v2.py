from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.core.db import Database, SCHEMA_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Photo Indexer DB to v2")
    parser.add_argument("db", type=Path, help="Path to SQLite DB")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()

    if version == SCHEMA_VERSION:
        print(f"DB already at schema v{SCHEMA_VERSION}")
        return 0

    if version != 1:
        print(f"Unsupported schema version: {version}")
        return 1

    db = Database(args.db)
    db.close()

    conn = sqlite3.connect(args.db)
    new_version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()

    if new_version != SCHEMA_VERSION:
        print(f"Migration failed; expected v{SCHEMA_VERSION}, got v{new_version}")
        return 1

    print(f"Migration complete: v{version} -> v{new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
