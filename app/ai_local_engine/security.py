"""التحقق من عناوين الاتصال — محلي فقط افتراضياً."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.ai_local_engine.exceptions import (
    AIConfigurationError,
    AIExternalConnectionBlockedError,
)

_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_BLOCKED_CLOUD_HINTS = (
    "openai.com",
    "api.openai.com",
    "anthropic.com",
    "googleapis.com",
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "api.mistral.ai",
    "cohere.ai",
    "azure.com",
    "huggingface.co",
)


def _host_is_private_or_loopback(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if host in _LOCAL_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            return True
    return False


def validate_ai_base_url(base_url: str, *, allow_internal_network: bool = False) -> str:
    """
    يتحقق من أن العنوان محلي (أو شبكة داخلية إن صُرح بها).
    يعيد العنوان منظّفاً بدون شرطة مائلة أخيرة.
    """
    raw = (base_url or "").strip()
    if not raw:
        raise AIConfigurationError("عنوان الخادم المحلي مطلوب.")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise AIConfigurationError("يُسمح فقط بعناوين http أو https.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise AIConfigurationError("تعذر قراءة اسم المضيف من عنوان الخادم.")

    host_l = host.lower()
    for hint in _BLOCKED_CLOUD_HINTS:
        if hint in host_l or host_l.endswith(hint):
            raise AIExternalConnectionBlockedError()

    is_loopback = host in _LOCAL_HOSTNAMES
    if not is_loopback:
        try:
            ip = ipaddress.ip_address(host)
            is_loopback = bool(ip.is_loopback)
        except ValueError:
            is_loopback = False

    if is_loopback:
        return raw.rstrip("/")

    if not allow_internal_network:
        raise AIExternalConnectionBlockedError()

    if not _host_is_private_or_loopback(host):
        raise AIExternalConnectionBlockedError()

    return raw.rstrip("/")


def assert_no_cloud_provider(provider: str) -> None:
    """يمنع اختيار مزودين سحابيين بالاسم."""
    p = (provider or "").strip().lower()
    blocked = {"openai", "anthropic", "gemini", "google", "azure", "groq", "mistral", "cohere"}
    if p in blocked:
        raise AIExternalConnectionBlockedError(
            "تم منع استخدام مزود سحابي. استخدم مزوداً محلياً فقط (Ollama / LM Studio / llama.cpp)."
        )
