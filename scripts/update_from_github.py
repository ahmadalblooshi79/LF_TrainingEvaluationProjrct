"""Safe GitHub update: pull code, keep local exercise data untouched.

Stop the running server before this script.
Usage: .venv\\Scripts\\python.exe scripts/update_from_github.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ITEMS = (
    "exercises.db",
    "exercises.db-wal",
    "exercises.db-shm",
    "exercise_store",
    "instance",
)


def _copy_item(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return
    shutil.copy2(src, dst)


def _backup(stamp: str) -> Path:
    dest = ROOT / "backups" / "pre-pull" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for name in DATA_ITEMS:
        _copy_item(ROOT / name, dest / name)
    return dest


def _restore(backup: Path) -> None:
    for name in DATA_ITEMS:
        src = backup / name
        if not src.exists():
            continue
        _copy_item(src, ROOT / name)


def _git_pull() -> int:
    r = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=ROOT,
        check=False,
    )
    return int(r.returncode)


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"[INFO] Backing up local exercise data to backups/pre-pull/{stamp}")
    backup = _backup(stamp)
    print("[INFO] Pulling code from GitHub (fast-forward only)")
    code = _git_pull()
    print("[INFO] Restoring local exercise data (database, archive, instance)")
    _restore(backup)
    if code != 0:
        print("[ERROR] git pull failed. Local exercise data was restored from the backup.")
        return code
    print("[OK] Code updated. Local exercises, users, and files were not replaced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
