"""نقطة دخول PyInstaller — تشغيل السيرفر بدون تثبيت Python على الجهاز."""
import os

os.environ.setdefault("LF_INSTALL_MODE", "1")
os.environ.setdefault("LF_OPEN_BROWSER", "1")
os.environ.setdefault("PORT", "8005")
os.environ.setdefault("HOST", "0.0.0.0")
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ.setdefault("FLASK_USE_RELOADER", "0")

import bootstrap_sys_path  # noqa: F401
from run import main

if __name__ == "__main__":
    main()
