"""Backfill org tables + stable student_ids from existing refs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.org_store import OrgStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map refs into country/province/school/class/students")
    parser.add_argument("--db", type=Path, default=None, help="Path to whozit.db (default: config)")
    args = parser.parse_args(argv)
    store = OrgStore(path=args.db)
    stats = store.backfill_from_refs()
    print(
        f"Backfill students={stats['students']} updated_refs={stats['updated_refs']} "
        f"skipped={stats['skipped']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
