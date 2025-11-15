# main.py
import sys
import csv
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView, QProgressBar, QFileDialog, QStatusBar,
    QMessageBox, QProgressDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer

from database import search_tickets, export_tickets

# ==================== AUTO-UPDATE CONFIG ====================
GITHUB_REPO = "samdavidson-wdw/tos_lookup" 
CURRENT_VERSION = "1.20"  
# ===========================================================

class UpdateChecker(QThread):
    update_available = Signal(str, str)  # version, download_url
    no_update = Signal()

    def run(self):
        try:
            response = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10)
            if response.status_code != 200:
                self.no_update.emit()
                return
            data = response.json()
            latest = data["tag_name"].lstrip("v")
            if latest > CURRENT_VERSION:
                asset = next((a for a in data["assets"] if a["name"].endswith(".exe")), None)
                if asset:
                    self.update_available.emit(latest, asset["browser_download_url"])
                else:
                    self.no_update.emit()
            else:
                self.no_update.emit()
        except:
            self.no_update.emit()

class Downloader(QThread):
    progress = Signal(int, int)  # current, total
    finished = Signal(str)       # installer path
    error = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            response = requests.get(self.url, stream=True)
            total = int(response.headers.get('content-length', 0))
            path = Path("update_installer.exe")
            downloaded = 0
            with open(path, "wb") as f:
                for chunk in response.iter_content(1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)
            self.finished.emit(str(path))
        except Exception as e:
            self.error.emit(str(e))

class SearchWorker(QThread):
    finished = Signal(dict)
    def __init__(self, search, status, page):
        super().__init__()
        self.search = search
        self.status = status
        self.page = page
    def run(self):
        result = search_tickets(self.search, self.status, self.page)
        self.finished.emit(result)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tickets Dashboard")
        self.resize(1100, 700)
        self.current_page = 1
        self.total_pages = 1
        self.last_search = ""
        self.last_status = "All"

        # Theme
        self.config_path = Path("config.json")
        self.dark_mode = self.load_theme()
        self.styles = {
            "dark": Path(__file__).parent / "ui" / "style.qss",
            "light": Path(__file__).parent / "ui" / "light.qss"
        }

        self.init_ui()
        self.apply_theme()
        self.check_for_updates()  # AUTO-UPDATE ON START
        self.refresh()

    # === Theme Methods (unchanged) ===
    def load_theme(self) -> bool:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return data.get("dark_mode", True)
            except:
                return True
        return True

    def save_theme(self):
        data = {"dark_mode": self.dark_mode}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.save_theme()
        self.apply_theme()

    def apply_theme(self):
        theme = "dark" if self.dark_mode else "light"
        path = self.styles[theme]
        if path.exists():
            self.setStyleSheet(path.read_text(encoding="utf-8"))
        self.theme_toggle.setChecked(self.dark_mode)

    # === AUTO-UPDATE ===
    def check_for_updates(self):
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self.on_update_available)
        self.update_checker.no_update.connect(lambda: None)
        self.update_checker.start()

    def on_update_available(self, version: str, url: str):
        reply = QMessageBox.question(
            self, "Update Available",
            f"Version {version} is available!\n\nDownload and install now?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.start_download(url)

    def start_download(self, url: str):
        self.progress_dialog = QProgressDialog("Downloading update...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowTitle("Updating...")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.canceled.connect(lambda: self.downloader.terminate())

        self.downloader = Downloader(url)
        self.downloader.progress.connect(self.update_progress)
        self.downloader.finished.connect(self.on_download_complete)
        self.downloader.error.connect(lambda msg: QMessageBox.critical(self, "Error", f"Download failed:\n{msg}"))
        self.downloader.start()

    def update_progress(self, current: int, total: int):
        if total > 0:
            percent = int(current * 100 / total)
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(f"Downloading... {current // 1024} KB / {total // 1024} KB")

    def on_download_complete(self, installer_path: str):
        self.progress_dialog.close()
        reply = QMessageBox.information(
            self, "Update Ready",
            "Update downloaded. The app will now restart and install the new version.",
            QMessageBox.Ok
        )
        if reply == QMessageBox.Ok:
            self.install_update(installer_path)

    def install_update(self, installer_path: str):
        try:
            subprocess.Popen([installer_path, "/SILENT", "/CLOSEAPPLICATIONS"])
            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self, "Install Failed", f"Could not start installer:\n{e}")

    # === UI (unchanged) ===
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # === Search Bar ===
        search_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tickets...")
        self.search_input.returnPressed.connect(self.on_search)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "Resolved", "Assigned", "Pending", "Work in Progress", "Cancelled", "Closed"])
        self.status_combo.currentTextChanged.connect(self.on_search)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.on_search)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setObjectName("exportBtn")
        self.export_btn.clicked.connect(self.export_csv)

        self.theme_toggle = QPushButton()
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.setFixedSize(50, 28)
        self.theme_toggle.clicked.connect(self.toggle_theme)

        search_bar.addWidget(QLabel("Search:"))
        search_bar.addWidget(self.search_input, 1)
        search_bar.addWidget(QLabel("Status:"))
        search_bar.addWidget(self.status_combo)
        search_bar.addWidget(self.refresh_btn)
        search_bar.addWidget(self.export_btn)
        search_bar.addWidget(QLabel("Theme:"))
        search_bar.addWidget(self.theme_toggle)

        layout.addLayout(search_bar)

        # === Stats ===
        self.stats_bar = QHBoxLayout()
        self.stats_labels = {}
        for key, label in [
            ("total", "Total"), ("resolved", "Resolved"),
            ("inProgress", "In Progress"), ("pending", "Pending"), ("cancelled", "Cancelled")
        ]:
            lbl = QLabel()
            self.stats_labels[key] = lbl
            self.stats_bar.addWidget(QLabel(f"{label}:"))
            self.stats_bar.addWidget(lbl)
            self.stats_bar.addStretch()
        layout.addLayout(self.stats_bar)

        # === Table ===
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Assignee", "Description", "Status", "Created", "Type"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        # === Pagination ===
        pag_layout = QHBoxLayout()
        self.page_label = QLabel()
        self.prev_btn = QPushButton("Prev")
        self.next_btn = QPushButton("Next")
        self.prev_btn.clicked.connect(lambda: self.go_page(self.current_page - 1))
        self.next_btn.clicked.connect(lambda: self.go_page(self.current_page + 1))

        pag_layout.addWidget(self.page_label)
        pag_layout.addStretch()
        pag_layout.addWidget(self.prev_btn)
        pag_layout.addWidget(self.next_btn)
        layout.addLayout(pag_layout)

        # === Progress & Status ===
        self.progress = QProgressBar()
        self.progress.setMaximum(0)
        self.progress.setMinimum(0)
        self.progress.setFixedHeight(0)
        layout.addWidget(self.progress)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        QTimer.singleShot(100, self.update_toggle_style)

    def update_toggle_style(self):
        self.theme_toggle.setStyleSheet(self.get_toggle_style())

    def get_toggle_style(self):
        return """
        QPushButton {
            background-color: #555;
            border-radius: 14px;
            border: none;
        }
        QPushButton::checked {
            background-color: #0d99ff;
        }
        QPushButton::after {
            content: '';
            position: absolute;
            width: 20px; height: 20px;
            border-radius: 10px;
            background: white;
            left: 4px; top: 4px;
            transition: 0.2s;
        }
        QPushButton::checked::after {
            transform: translateX(22px);
        }
        """

    # === Search & Pagination ===
    def on_search(self):
        self.current_page = 1
        self.refresh()

    def go_page(self, page):
        self.current_page = max(1, page)
        self.refresh()

    def refresh(self):
        search = self.search_input.text()
        status = self.status_combo.currentText()
        self.last_search, self.last_status = search, status

        self.progress.setMaximum(0)
        self.progress.show()
        self.worker = SearchWorker(search, status, self.current_page)
        self.worker.finished.connect(self.on_data_loaded)
        self.worker.start()

    def on_data_loaded(self, data):
        self.progress.hide()
        tickets = data["tickets"]
        total = data["total"]
        stats = data["stats"]

        self.total_pages = max(1, (total + 49) // 50)
        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < self.total_pages)

        for key in self.stats_labels:
            value = stats.get(key, 0)
            self.stats_labels[key].setText(f"<b>{value}</b>")

        self.table.setRowCount(len(tickets))
        for i, t in enumerate(tickets):
            self.table.setItem(i, 0, QTableWidgetItem(t["id"]))
            self.table.setItem(i, 1, QTableWidgetItem(t["assignee"]))
            self.table.setItem(i, 2, QTableWidgetItem(t["shortDescription"]))
            self.table.setItem(i, 3, QTableWidgetItem(t["status"]))
            self.table.setItem(i, 4, QTableWidgetItem(t["createdAt"]))
            self.table.setItem(i, 5, QTableWidgetItem(t["type"]))

        self.status_bar.showMessage(f"Showing {len(tickets)} of {total} tickets")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Tickets", "tickets_export.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            tickets = export_tickets(self.last_search, self.last_status)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Assignee", "Description", "Status", "Created", "Type"])
                for t in tickets:
                    writer.writerow([
                        t["id"], t["assignee"], t["shortDescription"],
                        t["status"], t["createdAt"], t["type"]
                    ])
            self.status_bar.showMessage(f"Exported {len(tickets)} tickets to {path}", 5000)
        except Exception as e:
            self.status_bar.showMessage(f"Export failed: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())