from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QLockFile, QDir, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSystemTrayIcon, QToolBar)

from . import discovery
from .config import APP_NAME, CONFIG_DIR, Config
from .discovery import Printer
from .monitor import PrinterMonitor

WAIT_PAGE = """
<html><body style="background:#1e1e1e;color:#ddd;font-family:Segoe UI,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><div style="font-size:28px;margin-bottom:12px">{title}</div>
<div style="font-size:15px;color:#999">{text}</div></div></body></html>
"""


def make_icon(color: str = "#2196f3") -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "F")
    p.end()
    return QIcon(pix)


class DiscoveryThread(QThread):
    found = Signal(object)  # Printer | None

    def __init__(self, last_ip: str | None, extra_subnets: list[str], parent=None):
        super().__init__(parent)
        self._last_ip = last_ip
        self._extra = extra_subnets
        self.stop_event = threading.Event()

    def run(self):
        self.found.emit(discovery.discover(self._last_ip, self._extra, self.stop_event))


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.printer: Printer | None = None
        self._scan: DiscoveryThread | None = None
        self._quitting = False
        self._hint_shown = False

        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.icon_ok, self.icon_wait = make_icon("#2196f3"), make_icon("#888888")
        self.setWindowIcon(self.icon_ok)

        # Отдельный постоянный профиль, чтобы настройки Fluidd (localStorage) сохранялись.
        self.profile = QWebEngineProfile("fluidd", self)
        self.profile.setPersistentStoragePath(str(CONFIG_DIR / "web"))
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(self.profile, self.view))
        self.setCentralWidget(self.view)

        tb = QToolBar("Панель", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction("⟳ Обновить", self.view.reload)
        tb.addAction("🔍 Найти принтер", self.rescan)
        tb.addAction("✎ Указать IP", self.ask_ip)
        tb.addAction("🌐 В браузере", self.open_in_browser)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)

        self.tray = QSystemTrayIcon(self.icon_wait, self)
        menu = QMenu()
        menu.addAction("Открыть", self.show_window)
        menu.addAction("Найти принтер", self.rescan)
        menu.addAction("Открыть в браузере", self.open_in_browser)
        menu.addSeparator()
        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

        self.monitor = PrinterMonitor(config.poll_interval_sec, config.progress_notifications, self)
        self.monitor.notify.connect(self.notify)
        self.monitor.status_changed.connect(self._set_status)
        self.monitor.lost.connect(self._on_lost)

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.rescan)

        self.rescan()

    # ---------- поиск ----------
    def rescan(self):
        if self._scan is not None and self._scan.isRunning():
            return
        self._retry.stop()
        self.monitor.stop()
        self._set_status("Поиск принтера в сети…")
        self.tray.setIcon(self.icon_wait)
        if self.printer is None:
            self._show_wait("Поиск принтера…", "Сканирую локальную сеть, это займёт несколько секунд")
        self._scan = DiscoveryThread(self.config.last_ip, self.config.extra_subnets, self)
        self._scan.found.connect(self._on_found)
        self._scan.finished.connect(self._scan.deleteLater)
        self._scan.start()

    def _on_found(self, printer: Printer | None):
        self._scan = None
        if self._quitting:
            return
        if printer is None:
            self.printer = None
            secs = int(self.config.rescan_interval_sec)
            self._set_status(f"Принтер не найден, повтор через {secs} с")
            self._show_wait("Принтер не найден",
                            f"Включите принтер или проверьте Wi-Fi. Повторный поиск через {secs} с")
            self._retry.start(secs * 1000)
            return
        changed = self.printer is None or self.printer.ip != printer.ip
        self.printer = printer
        self.config.last_ip = printer.ip
        self.config.save()
        self.tray.setIcon(self.icon_ok)
        self.setWindowTitle(f"{APP_NAME} — {printer.title} ({printer.ip})")
        if changed or self.view.url().host() != printer.ip:
            self.view.setUrl(QUrl(printer.ui_url))
        self.notify("Принтер подключён", f"{printer.title}: {printer.ui_url}", False)
        self.monitor.start(printer)

    def _on_lost(self):
        self.tray.setIcon(self.icon_wait)
        self._set_status("Связь потеряна, ищу принтер…")
        self._retry.start(int(self.config.rescan_interval_sec * 1000))

    def ask_ip(self):
        ip, ok = QInputDialog.getText(self, "Адрес принтера", "IP-адрес принтера:",
                                      text=self.config.last_ip or "")
        ip = ip.strip().removeprefix("http://").split("/")[0].split(":")[0]
        if not ok or not ip:
            return
        printer = discovery.probe(ip, connect_timeout=2.0)
        if printer is None:
            QMessageBox.warning(self, APP_NAME, f"По адресу {ip} Moonraker/Klipper не отвечает.")
            return
        self.monitor.stop()
        self._on_found(printer)

    # ---------- UI ----------
    def _show_wait(self, title: str, text: str):
        self.view.setHtml(WAIT_PAGE.format(title=title, text=text))

    def _set_status(self, text: str):
        where = f"{self.printer.ip}  |  " if self.printer else ""
        self.status_label.setText(where + text)
        self.tray.setToolTip(f"{APP_NAME}\n{where}{text}"[:127])

    def notify(self, title: str, text: str, is_error: bool = False):
        icon = QSystemTrayIcon.MessageIcon.Critical if is_error else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, text, icon, 10000)

    def open_in_browser(self):
        if self.printer:
            QDesktopServices.openUrl(QUrl(self.printer.ui_url))

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def closeEvent(self, event):
        if self._quitting:
            event.accept()
            return
        # Закрытие окна сворачивает в трей — уведомления продолжают приходить.
        event.ignore()
        self.hide()
        if not self._hint_shown:
            self._hint_shown = True
            self.notify(APP_NAME, "Приложение работает в трее. Выход — через меню значка.")

    def quit(self):
        self._quitting = True
        self.monitor.stop()
        if self._scan is not None:
            self._scan.stop_event.set()
            self._scan.wait(3000)
        self.tray.hide()
        QApplication.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(QDir(str(CONFIG_DIR)).filePath("app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "Приложение уже запущено (см. значок в трее).")
        return 0

    window = MainWindow(Config.load())
    window.show()
    return app.exec()
