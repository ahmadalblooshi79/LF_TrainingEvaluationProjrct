"""CLI for Agentic AI Foundation migration (English messages for Windows PowerShell).

Commands:
  migrate-agentic-foundation
  verify-agentic-migration
  rollback-agentic-foundation
  backup-db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agentic AI Foundation DB tools")
    parser.add_argument(
        "command",
        choices=[
            "migrate-agentic-foundation",
            "verify-agentic-migration",
            "rollback-agentic-foundation",
            "backup-db",
        ],
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip automatic backup before migrate (not recommended)",
    )
    parser.add_argument(
        "--restore-from",
        type=str,
        default="",
        help="Backup file path for rollback restore (optional)",
    )
    parser.add_argument(
        "--drop-tables-only",
        action="store_true",
        help="On rollback: drop agentic tables without restoring a backup file",
    )
    args = parser.parse_args(argv)

    from app.ai_agentic.exceptions import MigrationSafetyError
    from app.ai_agentic.migration import (
        create_database_backup,
        latest_agentic_backup,
        migrate_agentic_foundation,
        restore_database_from_backup,
        rollback_agentic_foundation,
        verify_agentic_migration,
    )

    try:
        if args.command == "backup-db":
            path = create_database_backup(reason="manual")
            print(f"OK backup created: {path}")
            return 0

        if args.command == "verify-agentic-migration":
            result = verify_agentic_migration()
            print(f"OK={result['ok']} present={result['present']} missing={result['missing']}")
            return 0 if result["ok"] else 2

        if args.command == "migrate-agentic-foundation":
            result = migrate_agentic_foundation(skip_backup=bool(args.skip_backup))
            print(f"OK migration complete backup={result.get('backup_path')}")
            print(f"verification={result.get('verification')}")
            print(f"legacy_counts={result.get('after_counts')}")
            return 0

        if args.command == "rollback-agentic-foundation":
            if args.drop_tables_only:
                result = rollback_agentic_foundation(drop_tables=True)
                print(f"OK dropped tables={result.get('dropped')}")
                return 0
            src = args.restore_from.strip()
            if not src:
                latest = latest_agentic_backup()
                if not latest:
                    print("ERROR: no backup found; pass --restore-from or use --drop-tables-only")
                    return 1
                src = str(latest)
            restored = restore_database_from_backup(src)
            print(f"OK restored database from {src} -> {restored}")
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
