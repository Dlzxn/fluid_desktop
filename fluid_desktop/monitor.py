"""Опрос Moonraker и генерация уведомлений по смене состояния принтера."""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .discovery import Printer

QUERY = "/printer/objects/query?webhooks&print_stats&display_status&virtual_sdcard"
FAILURES_BEFORE_LOST = 3
PROGRESS_MILESTONES = (25, 50, 75)

STATE_NAMES = {
    "standby": "Ожидание",
    "printing": "Печать",
    "paused": "Пауза",
    "complete": "Завершено",
    "cancelled": "Отменено",
    "error": "Ошибка",
}


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h} ч {m:02d} мин" if h else f"{m} мин {s:02d} с"


class PrinterMonitor(QObject):
    notify = Signal(str, str, bool)   # заголовок, текст, это ошибка
    status_changed = Signal(str)      # краткий статус для строки состояния/трея
    lost = Signal()                   # принтер перестал отвечать

    def __init__(self, interval_sec: float, progress_notifications: bool, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_sec * 1000))
        self._timer.timeout.connect(self._poll)
        self._progress_notifications = progress_notifications
        self._printer: Printer | None = None
        self._reply: QNetworkReply | None = None
        self._reset()

    def _reset(self):
        self._failures = 0
        self._klippy_state: str | None = None
        self._print_state: str | None = None
        self._milestone = 0

    def start(self, printer: Printer):
        self.stop()
        self._printer = printer
        self._reset()
        self._timer.start()
        self._poll()

    def stop(self):
        self._timer.stop()
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        self._printer = None

    def _poll(self):
        if self._printer is None or self._reply is not None:
            return
        req = QNetworkRequest(QUrl(self._printer.api_url + QUERY))
        req.setTransferTimeout(4000)
        self._reply = self._nam.get(req)
        self._reply.finished.connect(self._on_reply)

    def _on_reply(self):
        reply, self._reply = self._reply, None
        if reply is None:
            return
        reply.deleteLater()
        if self._printer is None:
            return
        data = None
        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))["result"]["status"]
            except (ValueError, KeyError, TypeError):
                data = None
        if data is None:
            # Пока Klipper перезапускается, Moonraker может вернуть 503 — это не потеря связи.
            if reply.error() != QNetworkReply.NetworkError.NoError and reply.attribute(
                    QNetworkRequest.Attribute.HttpStatusCodeAttribute):
                self._handle_klippy("startup", "Klipper недоступен")
                return
            self._failures += 1
            if self._failures >= FAILURES_BEFORE_LOST:
                printer = self._printer
                self.stop()
                self.notify.emit("Принтер отключился", f"{printer.title} не отвечает" if not printer.hostname else f"{printer.title} ({printer.ip}) не отвечает", True)
                self.lost.emit()
            return
        self._failures = 0
        self._handle(data)

    def _handle_klippy(self, state: str, message: str):
        prev, self._klippy_state = self._klippy_state, state
        if state == prev:
            return
        if state in ("shutdown", "error"):
            self.notify.emit("Klipper: ошибка", message or state, True)
        elif state == "ready" and prev in ("shutdown", "error", "startup"):
            self.notify.emit("Klipper готов", "Принтер готов к работе", False)
        if state != "ready":
            self.status_changed.emit(f"Klipper: {state}")

    def _handle(self, status: dict):
        wh = status.get("webhooks", {})
        self._handle_klippy(wh.get("state", ""), wh.get("state_message", ""))
        if self._klippy_state != "ready":
            return

        ps = status.get("print_stats", {})
        state = ps.get("state", "")
        filename = ps.get("filename") or ""
        progress = status.get("display_status", {}).get("progress")
        if progress is None:
            progress = status.get("virtual_sdcard", {}).get("progress", 0)
        pct = int((progress or 0) * 100)

        prev, self._print_state = self._print_state, state
        if prev is not None and state != prev:
            self._on_transition(prev, state, filename, ps)

        if state == "printing":
            if self._progress_notifications and prev is not None:
                for mark in PROGRESS_MILESTONES:
                    if self._milestone < mark <= pct:
                        self.notify.emit(f"Печать: {mark}%", filename, False)
            self._milestone = max(self._milestone, pct)
            self.status_changed.emit(f"Печать {pct}% — {filename}")
        else:
            self.status_changed.emit(STATE_NAMES.get(state, state))

    def _on_transition(self, prev: str, state: str, filename: str, ps: dict):
        duration = _fmt_duration(ps.get("print_duration", 0))
        if state == "printing":
            if prev == "paused":
                self.notify.emit("Печать продолжена", filename, False)
            else:
                self._milestone = 0
                self.notify.emit("Печать началась", filename, False)
        elif state == "paused":
            self.notify.emit("Печать на паузе", filename, False)
        elif state == "complete":
            self.notify.emit("Печать завершена ✔", f"{filename}\nВремя: {duration}", False)
        elif state == "cancelled":
            self.notify.emit("Печать отменена", filename, False)
        elif state == "error":
            self.notify.emit("Ошибка печати", ps.get("message") or filename, True)
