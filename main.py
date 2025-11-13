# main.py
import sys
import csv
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView, QProgressBar, QFileDialog, QStatusBar
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from database import search_tickets, export_tickets

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
        self.refresh()

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
        self.status_combo.addItems(["All", "Resolved", "Assigned", "Pending", "Work in Progress", "Closed"])
        self.status_combo.currentTextChanged.connect(self.on_search)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.on_search)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setObjectName("exportBtn")
        self.export_btn.clicked.connect(self.export_csv)

        # === Theme Toggle ===
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
            ("inProgress", "In Progress"), ("pending", "Pending")
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

        # Timer to refresh toggle style
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

        # Update stats
        for key in self.stats_labels:
            value = stats.get(key, 0)
            self.stats_labels[key].setText(f"<b>{value}</b>")

        # Update table
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