"""تنظيف نص محافظ للاستخراج."""

from __future__ import annotations

import re


def clean_text_conservative(text: str) -> str:
    if text is None:
        return ""
    s = text.replace("\x00", "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # مسافات زائدة داخل السطر فقط
    s = "\n".join(re.sub(r"[ \t]+", " ", line).rstrip() for line in s.split("\n"))
    # تقليل الأسطر الفارغة المتتالية إلى سطرين كحد أقصى
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
