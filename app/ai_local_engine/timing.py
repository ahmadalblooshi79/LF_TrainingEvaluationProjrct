"""قياس مدة استجابة مزود الذكاء الاصطناعي — زمن الشبكة فقط."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RequestTiming:
    """زمن طلب HTTP واحد: من الإرسال حتى اكتمال استلام الجسم."""

    raw_milliseconds: int
    start_time: str
    end_time: str
    elapsed_seconds: float

    def to_debug_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "raw_milliseconds": self.raw_milliseconds,
        }


def _wall_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " UTC"


class HttpRequestTimer:
    """يقيس فقط نافذة إرسال الطلب واستلام آخر بايت."""

    def __init__(self) -> None:
        self._t0: float | None = None
        self._start_wall: str | None = None

    def start(self) -> None:
        self._start_wall = _wall_now()
        self._t0 = time.perf_counter()

    def stop(self) -> RequestTiming:
        t1 = time.perf_counter()
        end_wall = _wall_now()
        t0 = self._t0 if self._t0 is not None else t1
        elapsed = max(0.0, t1 - t0)
        raw_ms = int(round(elapsed * 1000.0))
        return RequestTiming(
            raw_milliseconds=raw_ms,
            start_time=self._start_wall or end_wall,
            end_time=end_wall,
            elapsed_seconds=elapsed,
        )


def format_duration_ms(ms: int | float | None) -> str:
    """عرض مدة الاستجابة للمستخدم وفق القواعد المطلوبة."""
    if ms is None:
        return "—"
    try:
        value = int(round(float(ms)))
    except (TypeError, ValueError):
        return "—"
    if value < 0:
        value = 0
    if value < 1000:
        return f"{value} ms"
    if value < 60_000:
        return f"{value / 1000.0:.2f} ثانية"
    minutes = value // 60_000
    seconds = (value % 60_000) / 1000.0
    if seconds < 0.05:
        return f"{minutes} دقيقة"
    # ثوانٍ بدون كسور زائدة إن كانت قريبة من عدد صحيح
    if abs(seconds - round(seconds)) < 0.05:
        return f"{minutes} دقيقة و {int(round(seconds))} ثانية"
    return f"{minutes} دقيقة و {seconds:.1f} ثانية"
