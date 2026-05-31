"""عناوين الشبكة المحلية لربط الأجهزة عبر LAN / Wi‑Fi."""

from __future__ import annotations

import socket


def lan_ipv4_addresses() -> list[str]:
    """عناوين IPv4 على الشبكة الداخلية (بدون loopback)."""
    found: list[str] = []

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip in found:
                continue
            found.append(ip)
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.5)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        if ip and not ip.startswith("127.") and ip not in found:
            found.insert(0, ip)
    except OSError:
        pass

    return found


def server_access_urls(*, host: str, port: int) -> list[str]:
    """روابط يفتحها العملاء من المتصفح."""
    urls: list[str] = []
    if host in ("0.0.0.0", "::", ""):
        for ip in lan_ipv4_addresses():
            urls.append(f"http://{ip}:{port}/")
        urls.append(f"http://127.0.0.1:{port}/")
    else:
        urls.append(f"http://{host}:{port}/")
    # إزالة التكرار مع الحفاظ على الترتيب
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def print_server_access_info(*, host: str, port: int) -> None:
    """طباعة تعليمات الربط في نافذة السيرفر."""
    urls = server_access_urls(host=host, port=port)
    lan = [u for u in urls if "127.0.0.1" not in u]
    print()
    print("=" * 60)
    print("  نظام تقييم التدريب — الخادم يعمل")
    print("=" * 60)
    print(f"  المنفذ: {port}")
    print()
    print("  على هذا الجهاز (السيرفر):")
    print(f"    {urls[-1] if urls else f'http://127.0.0.1:{port}/'}")
    print()
    if lan:
        print("  للأجهزة الأخرى (LAN / Wi‑Fi) — افتح المتصفح فقط:")
        for u in lan:
            print(f"    {u}")
    else:
        print("  للأجهزة الأخرى: استخدم عنوان IP هذا الجهاز على الشبكة")
        print(f"    http://<عنوان-IP-السيرفر>:{port}/")
    print()
    print("  لا حاجة لتنصيب على أجهزة العملاء — متصفح فقط.")
    print("=" * 60)
    print()
