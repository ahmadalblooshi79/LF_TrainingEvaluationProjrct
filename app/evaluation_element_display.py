"""تنسيق عمود «عناصر التقييم»: مستوى الإزاحة ولون نوع الترقيم (أرقام / حروف / بين قوسين …)."""

from __future__ import annotations

import re

# أرقام عربية شرقية → غربية للتحقق
_AR_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_RE_WS = re.compile(r"\s+")


def _strip_bidi(s: str) -> str:
    return (
        (s or "")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .replace("\ufeff", "")
        .strip()
    )


def _is_ascii_digits(t: str) -> bool:
    if not t:
        return False
    return bool(re.fullmatch(r"[0-9]+", t.translate(_AR_DIGIT_TRANS)))


def _only_arabic_letters(t: str) -> bool:
    if not t:
        return False
    if re.search(r"[0-9]", t.translate(_AR_DIGIT_TRANS)):
        return False
    return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", t))


def split_evaluation_element(element: str | None) -> dict[str, object]:
    """
    يُحدد بادئة الترقيم وبقية النص ومستوى الإزاحة (0–4) وفئة اللون.

    الإزاحة التراكمية من سطر الأرقام البسيط:
    0 — 1. / 2 / 3 –
    1 — أ. / ب.
    2 — (1)
    3 — (أ)
    4 — (أأ) أو (ب ب)
    """
    s = _strip_bidi(element or "")
    if not s:
        return {
            "element_prefix": "",
            "element_rest": "",
            "element_indent": 0,
            "element_prefix_kind": "plain",
        }

    # أرقام بين قوسين — برتقالي، مستوى 2
    m = re.match(r"^(\s*\(\s*[0-9٠-٩]+\s*\)\s*)", s)
    if m:
        pref = m.group(1)
        return {
            "element_prefix": pref,
            "element_rest": s[len(pref) :],
            "element_indent": 2,
            "element_prefix_kind": "pnum",
        }

    # أي محتوى بين قوسين — حروف أو مزدوج
    m = re.match(r"^(\s*\(\s*[^)]+\s*\)\s*)", s)
    if m:
        pref = m.group(1)
        inner_m = re.search(r"\(\s*([^)]*)\s*\)", pref)
        inner = (inner_m.group(1) if inner_m else "").strip()

        if inner and _is_ascii_digits(inner):
            # مثل (12) لو فات الفرع الأول — نعتبره أرقاماً بقوسين
            return {
                "element_prefix": pref,
                "element_rest": s[len(pref) :],
                "element_indent": 2,
                "element_prefix_kind": "pnum",
            }

        if _RE_WS.search(inner):
            parts = [p for p in _RE_WS.split(inner) if p]
            if len(parts) == 2 and all(_only_arabic_letters(p) for p in parts):
                return {
                    "element_prefix": pref,
                    "element_rest": s[len(pref) :],
                    "element_indent": 4,
                    "element_prefix_kind": "pdouble",
                }
        elif inner:
            # حرف واحد أو مدخل مع ط؛ مثل (أ) أو (جـ)
            if inner.endswith("ـ") and len(inner) <= 3 and _only_arabic_letters(inner):
                return {
                    "element_prefix": pref,
                    "element_rest": s[len(pref) :],
                    "element_indent": 3,
                    "element_prefix_kind": "pletter",
                }
            if len(inner) == 1 and _only_arabic_letters(inner):
                return {
                    "element_prefix": pref,
                    "element_rest": s[len(pref) :],
                    "element_indent": 3,
                    "element_prefix_kind": "pletter",
                }
            if len(inner) >= 2 and _only_arabic_letters(inner):
                return {
                    "element_prefix": pref,
                    "element_rest": s[len(pref) :],
                    "element_indent": 4,
                    "element_prefix_kind": "pdouble",
                }
        # أقواس غير مطابقة للأنماط — لا نستهلك؛ نتابع كنسخة عادية
        # (نترك s كما هو للفروع التالية)

    # حروف ثم نقطة — أزرق، مستوى 1
    m = re.match(
        r"^(\s*[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+\s*\.\s*)",
        s,
    )
    if m:
        pref = m.group(1)
        return {
            "element_prefix": pref,
            "element_rest": s[len(pref) :],
            "element_indent": 1,
            "element_prefix_kind": "letter",
        }

    # أرقام مع فاصل — أسود Bold، مستوى 0
    m = re.match(
        r"^(\s*[0-9٠-٩]+\s*(?:[.)\]:：،,]|\s*[-–—]\s*)?\s*)",
        s,
    )
    if m:
        pref = m.group(1)
        core = pref.translate(_AR_DIGIT_TRANS).strip()
        if core and core[0].isdigit():
            return {
                "element_prefix": pref,
                "element_rest": s[len(pref) :],
                "element_indent": 0,
                "element_prefix_kind": "num",
            }

    return {
        "element_prefix": "",
        "element_rest": s,
        "element_indent": 0,
        "element_prefix_kind": "plain",
    }


def enrich_eval_rows_element_styles(rows: list[dict]) -> list[dict]:
    """يُضاف لكل صف حقول العرض للترقيم."""
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        row.update(split_evaluation_element(row.get("element")))
        out.append(row)
    return out
