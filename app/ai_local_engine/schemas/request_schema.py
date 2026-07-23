"""مخططات الطلب."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GenerateTextRequest:
    prompt: str
    system_prompt: str = ""
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    context: dict[str, Any] | None = None
