"""عناوين الشبكة المحلية لربط الأجهزة عبر LAN / Wi‑Fi — مع تجاهل المحولات الافتراضية."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from typing import Any

# محولات تُستبعد من الاكتشاف (افتراضية / VPN / وهمية)
_IGNORED_ADAPTER_SUBSTRINGS = (
    "vmware",
    "virtualbox",
    "vbox",
    "hyper-v",
    "hyper v",
    "vethernet",
    "docker",
    "vpn",
    "loopback",
    "bluetooth",
    "wan miniport",
    "tap-",
    "tun ",
    "wintun",
    "npcap",
    "hamachi",
    "zero tier",
    "zerotier",
    "nordlynx",
    "tailscale",
    "openvpn",
    "pptp",
    "isatap",
    "teredo",
    "6to4",
    "pseudo-interface",
    "wireguard",
    "anyconnect",
    "fortinet",
    "softether",
    "sing-tun",
    "networx",
    "hotspot",
    "mobile broadband",
    "wi-fi direct",
    "wifi direct",
)

_WIFI_NAME_HINTS = ("wireless", "wi-fi", "wi fi", "wifi", "wlan", "802.11", "شبكة لاسلكية", "لاسلك")
_ETHERNET_NAME_HINTS = ("ethernet", "gigabit", "realtek", "intel", "ethernet", "إيثرنت", "سلكي")

_IPV4_RE = re.compile(
    r"(?:ipv4|عنوان\s*ipv4).*?[:：]\s*([\d.]+)",
    re.IGNORECASE,
)
_SUBNET_RE = re.compile(
    r"(?:subnet\s*mask|قناع).*?[:：]\s*([\d.]+)",
    re.IGNORECASE,
)
_GATEWAY_RE = re.compile(
    r"(?:default\s*gateway|البوابة).*?[:：]\s*([\d.]+)",
    re.IGNORECASE,
)
_DNS_RE = re.compile(
    r"(?:dns\s*servers?|خوادم\s*dns).*?[:：]\s*(.+)$",
    re.IGNORECASE,
)
_MAC_RE = re.compile(
    r"(?:physical\s*address|العنوان\s*الفعلي).*?[:：]\s*([0-9A-Fa-f\-]+)",
    re.IGNORECASE,
)
_SSID_RE = re.compile(
    r"(?:ssid).*?[:：]\s*(.+)$",
    re.IGNORECASE,
)


def _console_banner_enabled() -> bool:
    v = (os.environ.get("LF_SERVER_BANNER") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def _is_ignored_adapter(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return True
    return any(sub in n for sub in _IGNORED_ADAPTER_SUBSTRINGS)


def _adapter_kind(name: str) -> str:
    n = (name or "").lower()
    if any(h in n for h in _WIFI_NAME_HINTS):
        return "wifi"
    if any(h in n for h in _ETHERNET_NAME_HINTS):
        return "ethernet"
    return "other"


def _priority_rank(kind: str) -> int:
    if kind == "wifi":
        return 0
    if kind == "ethernet":
        return 1
    return 2


def _first_ipv4(text: str) -> str:
    m = re.search(r"\d+\.\d+\.\d+\.\d+", text or "")
    return m.group(0) if m else ""


def _is_continuation_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.search(r"[:：]", line) and not line.startswith((" ", "\t")):
        return False
    return line.startswith((" ", "\t")) and bool(_first_ipv4(line))


def _block_disconnected(lines: list[str]) -> bool:
    blob = "\n".join(lines).lower()
    if "media disconnected" in blob or "غير متصل" in blob:
        return True
    if "disconnected" in blob and not _IPV4_RE.search(blob):
        return True
    return False


def _parse_ipconfig_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped and not stripped.startswith((" ", "\t")) and stripped.endswith(":"):
            if current_name is not None:
                blocks.append((current_name, current_lines))
            current_name = stripped[:-1].strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        blocks.append((current_name, current_lines))

    adapters: list[dict[str, Any]] = []
    for name, lines in blocks:
        if _is_ignored_adapter(name):
            continue
        if _block_disconnected(lines):
            continue

        ipv4 = subnet = gateway = mac = ssid = ""
        dns: list[str] = []

        for i, line in enumerate(lines):
            m4 = _IPV4_RE.search(line)
            if m4:
                ipv4 = m4.group(1).strip()
            ms = _SUBNET_RE.search(line)
            if ms:
                subnet = ms.group(1).strip()
            low = line.lower()
            if "default gateway" in low or "البوابة" in line:
                gateway = _first_ipv4(line)
                if not gateway:
                    for cont in lines[i + 1 : i + 5]:
                        if _is_continuation_line(cont):
                            gateway = _first_ipv4(cont)
                            if gateway:
                                break
            mm = _MAC_RE.search(line)
            if mm:
                mac = mm.group(1).strip().replace("-", ":").upper()
            md = _DNS_RE.search(line)
            if md:
                val = md.group(1).strip()
                if val and val not in dns:
                    dns.append(val.split("(")[0].strip())
            mssid = _SSID_RE.search(line)
            if mssid:
                ssid = mssid.group(1).strip()

        if not ipv4 or ipv4.startswith("127."):
            continue

        kind = _adapter_kind(name)
        adapters.append(
            {
                "adapter_name": name,
                "kind": kind,
                "connection_type": "WiFi" if kind == "wifi" else ("Ethernet" if kind == "ethernet" else "Other"),
                "ip_address": ipv4,
                "ipv4": ipv4,
                "subnet_mask": subnet,
                "gateway": gateway,
                "dns": dns,
                "mac_address": mac,
                "ssid": ssid,
            }
        )

    adapters.sort(key=lambda a: (_priority_rank(a["kind"]), a["adapter_name"]))
    return adapters


def _discover_adapters_psutil() -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore
    except ImportError:
        return []

    stats = psutil.net_if_stats()
    out: list[dict[str, Any]] = []
    for if_name, addrs in psutil.net_if_addrs().items():
        if _is_ignored_adapter(if_name):
            continue
        st = stats.get(if_name)
        if st is not None and not st.isup:
            continue

        ipv4 = subnet = mac = ""
        for addr in addrs:
            fam = getattr(addr, "family", None)
            if fam == socket.AF_INET:
                ipv4 = (addr.address or "").strip()
                subnet = (addr.netmask or "").strip()
            elif hasattr(psutil, "AF_LINK") and fam == psutil.AF_LINK:
                mac = (addr.address or "").strip().replace("-", ":").upper()

        if not ipv4 or ipv4.startswith("127."):
            continue

        kind = _adapter_kind(if_name)
        out.append(
            {
                "adapter_name": if_name,
                "kind": kind,
                "connection_type": "WiFi" if kind == "wifi" else ("Ethernet" if kind == "ethernet" else "Other"),
                "ip_address": ipv4,
                "ipv4": ipv4,
                "subnet_mask": subnet,
                "gateway": "",
                "dns": [],
                "mac_address": mac,
                "ssid": "",
            }
        )

    out.sort(key=lambda a: (_priority_rank(a["kind"]), a["adapter_name"]))
    return out


def _merge_adapter_details(ipconfig_adapters: list[dict], psutil_adapters: list[dict]) -> list[dict[str, Any]]:
    if ipconfig_adapters:
        return ipconfig_adapters
    return psutil_adapters


def discover_network_adapters() -> list[dict[str, Any]]:
    """اكتشاف المحولات الفعّالة: Wi‑Fi ثم Ethernet ثم غير ذلك."""
    override = (os.environ.get("LF_SERVER_IP") or "").strip()
    ipconfig_adapters: list[dict[str, Any]] = []

    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["ipconfig", "/all"],
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            ipconfig_adapters = _parse_ipconfig_blocks(out)
        except (OSError, subprocess.SubprocessError):
            pass

    psutil_adapters = _discover_adapters_psutil()
    adapters = _merge_adapter_details(ipconfig_adapters, psutil_adapters)

    if override:
        found = next((a for a in adapters if a.get("ipv4") == override), None)
        if found:
            adapters = [found] + [a for a in adapters if a is not found]
        else:
            adapters.insert(
                0,
                {
                    "adapter_name": "LF_SERVER_IP (override)",
                    "kind": "wifi",
                    "connection_type": "WiFi",
                    "ip_address": override,
                    "ipv4": override,
                    "subnet_mask": "",
                    "gateway": "",
                    "dns": [],
                    "mac_address": "",
                    "ssid": "",
                },
            )

    return adapters


def primary_network_adapter() -> dict[str, Any] | None:
    adapters = discover_network_adapters()
    return adapters[0] if adapters else None


def primary_lan_ipv4() -> str:
    override = (os.environ.get("LF_SERVER_IP") or "").strip()
    if override:
        return override
    adapter = primary_network_adapter()
    if adapter and adapter.get("ipv4"):
        return str(adapter["ipv4"])
    return "127.0.0.1"


def lan_ipv4_addresses() -> list[str]:
    """عناوين IPv4 للمحولات الفعلية (Wi‑Fi أولاً) — بدون VMware/VPN/افتراضية."""
    override = (os.environ.get("LF_SERVER_IP") or "").strip()
    ips: list[str] = []
    if override:
        ips.append(override)
    for a in discover_network_adapters():
        ip = (a.get("ipv4") or "").strip()
        if ip and not ip.startswith("127.") and ip not in ips:
            ips.append(ip)
    return ips


def network_details() -> dict[str, Any]:
    """تفاصيل المحول الأساسي للعرض في لوحة الخادم."""
    adapter = primary_network_adapter() or {}
    return {
        "adapter_name": adapter.get("adapter_name", ""),
        "ip_address": adapter.get("ip_address", primary_lan_ipv4()),
        "ipv4": adapter.get("ipv4", primary_lan_ipv4()),
        "subnet_mask": adapter.get("subnet_mask", ""),
        "gateway": adapter.get("gateway", ""),
        "dns": adapter.get("dns") or [],
        "mac_address": adapter.get("mac_address", ""),
        "ssid": adapter.get("ssid", ""),
        "connection_type": adapter.get("connection_type", "Unknown"),
        "kind": adapter.get("kind", ""),
    }


def server_access_urls(*, host: str, port: int) -> list[str]:
    """روابط يفتحها العملاء من المتصفح."""
    urls: list[str] = []
    if host in ("0.0.0.0", "::", ""):
        for ip in lan_ipv4_addresses():
            urls.append(f"http://{ip}:{port}/")
        urls.append(f"http://127.0.0.1:{port}/")
    else:
        bind_ip = host if not host.startswith("127.") else primary_lan_ipv4()
        urls.append(f"http://{bind_ip}:{port}/")
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def print_server_access_info(*, host: str, port: int) -> None:
    """طباعة عناوين الوصول في الطرفية."""
    if not _console_banner_enabled():
        return
    urls = server_access_urls(host=host, port=port)
    primary = primary_lan_ipv4()
    lan = [u for u in urls if "127.0.0.1" not in u]
    adapter = primary_network_adapter()
    adapter_name = (adapter or {}).get("adapter_name", "")
    print()
    print("=" * 60)
    print("  LF Training Evaluation - server running")
    print("=" * 60)
    print(f"  Port: {port}")
    print(f"  Listen: {host or '0.0.0.0'} (LAN + Wi-Fi)")
    if adapter_name:
        print(f"  Adapter: {adapter_name}")
    print(f"  Primary IP: {primary}")
    print()
    print("  This PC:")
    print(f"    http://{primary}:{port}/")
    print()
    if lan:
        print("  Other devices (browser only, same network):")
        for u in lan:
            print(f"    {u}")
    else:
        print(f"  Other devices: http://<{primary}>:{port}/")
    print("=" * 60)
    print()
