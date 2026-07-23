"""تنسيق العرض لواجهة Agentic (مدة، قيم فارغة)."""

from __future__ import annotations


def dash(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str) and not value.strip():
        return "—"
    return str(value)


def format_duration_ms(ms: int | float | None) -> str:
    """عرض مفهوم للمستخدم مع الإبقاء على ms في API/DB."""
    if ms is None:
        return "—"
    try:
        n = float(ms)
    except (TypeError, ValueError):
        return "—"
    if n < 0:
        return "—"
    if n < 1000:
        return f"{int(round(n))} مللي ثانية"
    seconds = n / 1000.0
    if seconds < 60:
        return f"{seconds:.1f} ثانية"
    minutes = int(seconds // 60)
    rem = seconds - minutes * 60
    return f"{minutes} د و {rem:.1f} ث"
