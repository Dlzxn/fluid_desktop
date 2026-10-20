"""Автообновление через GitHub Releases.

Берётся последний релиз репозитория, и если его версия новее текущей, из ассетов
выбирается установщик (*Setup*.exe). Он скачивается во временную папку и запускается
в тихом режиме, после чего приложение закрывается: Inno Setup заменит файлы и
снова запустит программу.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": f"FluiddDesktop/{__version__}"}


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    page_url: str
    installer_url: str
    installer_name: str


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_frozen() -> bool:
    """True, если запущена собранная (установленная) версия, а не исходники."""
    return getattr(sys, "frozen", False)


def fetch_latest(timeout: float = 10) -> Release | None:
    req = urllib.request.Request(API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe") and "setup" in name.lower():
            return Release(version=data.get("tag_name", "").lstrip("v"),
                           notes=data.get("body") or "",
                           page_url=data.get("html_url", ""),
                           installer_url=asset["browser_download_url"],
                           installer_name=name)
    return None


class UpdateCheckThread(QThread):
    available = Signal(object)  # Release
    failed = Signal(str)
    up_to_date = Signal()

    def run(self):
        try:
            release = fetch_latest()
        except Exception as e:  # сеть, лимиты API, кривой JSON — для проверки обновлений не критично
            self.failed.emit(str(e))
            return
        if release and parse_version(release.version) > parse_version(__version__):
            self.available.emit(release)
        else:
            self.up_to_date.emit()


class DownloadThread(QThread):
    progress = Signal(int)   # проценты
    done = Signal(str)       # путь к установщику
    failed = Signal(str)

    def __init__(self, release: Release, parent=None):
        super().__init__(parent)
        self.release = release

    def run(self):
        target = Path(tempfile.gettempdir()) / self.release.installer_name
        try:
            req = urllib.request.Request(self.release.installer_url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=30) as resp, open(target, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                read = 0
                while chunk := resp.read(256 * 1024):
                    f.write(chunk)
                    read += len(chunk)
                    if total:
                        self.progress.emit(int(read * 100 / total))
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.done.emit(str(target))


def run_installer(path: str) -> None:
    """Запускает установщик Inno Setup в тихом режиме, отвязанным от текущего процесса."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
