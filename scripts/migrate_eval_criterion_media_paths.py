"""Migrate criterion media from judges/ paths to unit/list/item paths.

English console messages (Windows PowerShell). Does not guess ownership.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import EVAL_CRITERION_MEDIA_DIR  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.eval_criterion_media import migrate_legacy_judge_media_records  # noqa: E402


def backup_media_dir() -> Path:
    src = Path(EVAL_CRITERION_MEDIA_DIR)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = src.parent / f"eval_criterion_media.bak-{stamp}"
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=False)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest


def write_report(report: dict, backup: Path) -> Path:
    out = ROOT / "instance" / (
        f"eval_criterion_media_migration_{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Criterion media path migration report",
        f"backup_dir={backup}",
        f"media_dir={EVAL_CRITERION_MEDIA_DIR}",
        f"total_old_files={report.get('total_old_files')}",
        f"migrated={report.get('migrated')}",
        f"left_legacy={report.get('left_legacy')}",
        f"already_new={report.get('already_new')}",
        f"missing_disk={report.get('missing_disk')}",
        f"broken_paths={report.get('broken_paths')}",
        f"migrated_ids={report.get('migrated_ids')}",
        f"left_ids={report.get('left_ids')}",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    print("Backing up media directory...")
    backup = backup_media_dir()
    print(f"Backup: {backup}")
    db = SessionLocal()
    try:
        report = migrate_legacy_judge_media_records(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    report_path = write_report(report, backup)
    print("Migration complete.")
    print(f"total_old_files={report['total_old_files']}")
    print(f"migrated={report['migrated']}")
    print(f"left_legacy={report['left_legacy']}")
    print(f"already_new={report['already_new']}")
    print(f"missing_disk={report['missing_disk']}")
    print(f"broken_paths={report['broken_paths']}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
