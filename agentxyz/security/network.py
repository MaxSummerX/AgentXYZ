"""Утилиты сетевой безопасности — защита от SSRF и обнаружение внутренних URL-адресов."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # NAT операторского класса
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / метаданные облака
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # уникальные локальные
    ipaddress.ip_network("fe80::/10"),  # link-local v6
]

_URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(addr in net for net in _BLOCKED_NETWORKS)


def validate_url_target(url: str) -> tuple[bool, str]:
    """Проверить, что URL безопасен для загрузки: схема, имя хоста и разрешённые IP-адреса.

    Args:
        url: URL-адрес для проверки.

    Returns:
        Кортеж (ok, error_message). Когда ok равно True, error_message пустой.
    """
    try:
        p = urlparse(url)
    except Exception as e:
        return False, str(e)

    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
    if not p.netloc:
        return False, "Missing domain"

    hostname = p.hostname
    if not hostname:
        return False, "Missing hostname"

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_private(addr):
            return (
                False,
                f"Blocked: {hostname} resolves to private/internal address {addr}",
            )

    return True, ""


def validate_resolved_url(url: str) -> tuple[bool, str]:
    """Проверить уже полученный URL (например, после перенаправления). Проверяет только IP, пропускает DNS.

    Args:
        url: URL-адрес для проверки.

    Returns:
        Кортеж (ok, error_message). Когда ok равно True, error_message пустой.
    """
    try:
        p = urlparse(url)
    except Exception:
        return True, ""

    hostname = p.hostname
    if not hostname:
        return True, ""

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private(addr):
            return False, f"Redirect target is a private address: {addr}"
    except ValueError:
        # hostname is a domain name, resolve it
        try:
            infos = socket.getaddrinfo(
                hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
        except socket.gaierror:
            return True, ""
        for info in infos:
            try:
                addr = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _is_private(addr):
                return (
                    False,
                    f"Redirect target {hostname} resolves to private address {addr}",
                )

    return True, ""


def contains_internal_url(command: str) -> bool:
    """Вернуть True, если командная строка содержит URL, указывающий на внутренний/приватный адрес.

    Args:
        command: Командная строка для проверки.

    Returns:
        True, если найден URL с внутренним/приватным адресом, иначе False.
    """
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        ok, _ = validate_url_target(url)
        if not ok:
            return True
    return False
