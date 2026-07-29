"""CLI for Training Center migration (English messages for PowerShell).

Commands:
  migrate-training-center
  verify-training-center-migration
  rollback-training-center
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Training Center DB tools")
    parser.add_argument(
        "command",
        choices=[
            "migrate-training-center",
            "verify-training-center-migration",
            "rollback-training-center",
        ],
    )
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--drop-tables-only", action="store_true")
    args = parser.parse_args(argv)

    from app.ai_training.migration import (
        MigrationSafetyError,
        migrate_training_center,
        rollback_training_center,
        verify_training_migration,
    )

    try:
        if args.command == "verify-training-center-migration":
            r = verify_training_migration()
            print(f"OK={r['ok']} present={r['present']} missing={r['missing']}")
            return 0 if r["ok"] else 2
        if args.command == "migrate-training-center":
            r = migrate_training_center(skip_backup=bool(args.skip_backup))
            print(f"OK migration backup={r.get('backup_path')} verification={r.get('verification')}")
            return 0
        if args.command == "rollback-training-center":
            r = rollback_training_center(drop_tables=True)
            print(f"OK dropped={r.get('dropped')}")
            return 0
    except MigrationSafetyError as exc:
        print(f"ERROR: {exc.user_message}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
