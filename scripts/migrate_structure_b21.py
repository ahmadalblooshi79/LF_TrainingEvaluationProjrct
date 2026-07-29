"""CLI for Phase B2.1 Military Structure migration (English console messages)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Military Structure B2.1 DB tools")
    parser.add_argument(
        "command",
        choices=[
            "migrate-structure-b21",
            "verify-structure-b21",
            "rollback-structure-b21",
        ],
    )
    parser.add_argument("--skip-backup", action="store_true")
    args = parser.parse_args(argv)

    from app.ai_training.structure_migration import (
        StructureMigrationError,
        migrate_structure_b21,
        rollback_structure_b21,
        verify_structure_migration,
    )

    try:
        if args.command == "verify-structure-b21":
            r = verify_structure_migration()
            print(f"OK={r['ok']} present={r['present']} missing={r['missing']} cols={r.get('missing_columns')}")
            return 0 if r["ok"] else 2
        if args.command == "migrate-structure-b21":
            r = migrate_structure_b21(skip_backup=bool(args.skip_backup))
            print(f"OK migration backup={r.get('backup_path')} verification={r.get('verification')}")
            return 0
        if args.command == "rollback-structure-b21":
            r = rollback_structure_b21(drop_tables=True)
            print(f"OK dropped={r.get('dropped')}")
            return 0
    except StructureMigrationError as exc:
        print(f"ERROR: {exc.user_message}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
