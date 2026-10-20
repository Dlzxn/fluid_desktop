"""Поиск принтера с Klipper/Moonraker (Elegoo Neptune 4 и т.п.) в локальной сети.

Порядок проверки:
  1. последний известный IP (из конфига);
  2. адреса из ARP-таблицы Windows (устройства, с которыми уже был обмен);
  3. полный перебор /24 всех локальных частных подсетей.

Хост считается принтером, если по адресу http://<ip>:<port>/server/info
отвечает Moonraker (в JSON есть поле klippy_state).
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable

API_PORTS = (7125, 80)
CONNECT_TIMEOUT = 0.4
HTTP_TIMEOUT = 2.0
MAX_WORKERS = 128


@dataclass(frozen=True)
class Printer:
    ip: str
    api_port: int
    hostname: str = ""

    @property
    def api_url(self) -> str:
        return f"http://{self.ip}:{self.api_port}" if self.api_port != 80 else f"http://{self.ip}"

    @property
    def ui_url(self) -> str:
        return f"http://{self.ip}/"

    @property
    def title(self) -> str:
        return self.hostname or self.ip


def _port_open(ip: str, port: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_json(url: str, timeout: float = HTTP_TIMEOUT) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None


def probe(ip: str, ports: Iterable[int] = API_PORTS, connect_timeout: float = CONNECT_TIMEOUT) -> Printer | None:
    """Проверяет, отвечает ли по адресу ip Moonraker. Возвращает Printer или None."""
    for port in ports:
        if not _port_open(ip, port, connect_timeout):
            continue
        base = f"http://{ip}:{port}"
        info = _get_json(f"{base}/server/info")
        result = (info or {}).get("result")
        if not isinstance(result, dict) or "klippy_state" not in result:
            continue
        hostname = ""
        pinfo = _get_json(f"{base}/printer/info")
        if pinfo and isinstance(pinfo.get("result"), dict):
            hostname = str(pinfo["result"].get("hostname") or "")
        return Printer(ip=ip, api_port=port, hostname=hostname)
    return None


def local_ipv4_addresses() -> list[str]:
    addrs: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    # Адрес интерфейса с маршрутом по умолчанию (пакеты реально не отправляются).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    result = []
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip.is_private and not ip.is_loopback and not ip.is_link_local:
            result.append(a)
    # 192.168.x.x — обычно домашний Wi-Fi, проверяем первыми.
    return sorted(result, key=lambda a: (not a.startswith("192.168."), a))


def local_networks(extra_subnets: Iterable[str] = ()) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    for a in local_ipv4_addresses():
        net = ipaddress.ip_network(f"{a}/24", strict=False)
        if net not in nets:
            nets.append(net)
    for s in extra_subnets:
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError:
            continue
        if net.version == 4 and net not in nets:
            nets.append(net)
    return nets


def arp_neighbors() -> list[str]:
    """IP-адреса из ARP-кэша (`arp -a`), без широковещательных/мультикаст."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, timeout=5, **kwargs).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    text = out.decode("utf-8", "replace")
    ips = []
    for m in re.finditer(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if ip.is_multicast or str(ip).endswith(".255") or not ip.is_private:
            continue
        if str(ip) not in ips:
            ips.append(str(ip))
    return ips


def _scan(ips: list[str], stop: threading.Event) -> Printer | None:
    if not ips:
        return None
    pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(ips)))
    try:
        futures = [pool.submit(lambda ip=ip: None if stop.is_set() else probe(ip)) for ip in ips]
        for fut in as_completed(futures):
            printer = fut.result()
            if printer:
                return printer
            if stop.is_set():
                return None
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def discover(last_ip: str | None = None,
             extra_subnets: Iterable[str] = (),
             stop: threading.Event | None = None) -> Printer | None:
    stop = stop or threading.Event()
    own = set(local_ipv4_addresses())
    nets = local_networks(extra_subnets)

    if last_ip:
        printer = probe(last_ip, connect_timeout=1.0)
        if printer:
            return printer

    def in_nets(ip: str) -> bool:
        addr = ipaddress.ip_address(ip)
        return any(addr in n for n in nets)

    tried = {last_ip} | own
    arp = [ip for ip in arp_neighbors() if ip not in tried and in_nets(ip)]
    printer = _scan(arp, stop)
    if printer or stop.is_set():
        return printer
    tried.update(arp)

    hosts = [str(h) for net in nets for h in net.hosts() if str(h) not in tried]
    return _scan(hosts, stop)


if __name__ == "__main__":
    print("Сети:", [str(n) for n in local_networks()])
    print("Найден:", discover())
