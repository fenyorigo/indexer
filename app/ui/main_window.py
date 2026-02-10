from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.config import AppConfig, load_config
from app.core.db import Database
from app.core.models import DirectorySelection, ScanResult
from app.core.scanner import scan
from app.core.tri_state import CHECKED, PARTIAL, UNCHECKED, compute_root_state


ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_IS_ROOT = Qt.ItemDataRole.UserRole + 1
ROLE_ROOT_MEDIA = Qt.ItemDataRole.UserRole + 2
ROLE_ROOT_SELF = Qt.ItemDataRole.UserRole + 3


class ScanWorker(QObject):
    finished = pyqtSignal(ScanResult)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(
        self,
        db_path: Path,
        config: AppConfig,
        root_path: Path,
        selections: list[DirectorySelection],
        dry_run: bool,
        changed_only: bool,
        errors_log_path: Optional[Path],
        db_path: Path,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.config = config
        self.root_path = root_path
        self.selections = selections
        self.dry_run = dry_run
        self.changed_only = changed_only
        self.errors_log_path = errors_log_path
        self.db_path = db_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            db = Database(self.db_path)
            summary = scan(
                db,
                self.config,
                self.root_path,
                self.selections,
                dry_run=self.dry_run,
                changed_only=self.changed_only,
                cancel_check=lambda: self._cancelled,
                progress_cb=lambda current, total, path: self.progress.emit(current, total, path),
                errors_log_path=self.errors_log_path,
                db_path=self.db_path,
            )
            db.close()
            self.finished.emit(summary)
        except Exception as exc:  # pragma: no cover - UI error path
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        from app import __version__

        self.setWindowTitle(f"Photo Indexer {__version__}")

        self.config = load_config(Path("config.yaml"))
        self.db: Optional[Database] = None
        self.db_path: Optional[Path] = None
        self.scan_root: Optional[Path] = None

        self.root_list = QTreeWidget()
        self.root_list.setHeaderLabels(["Indexed roots", "Status"])
        self.root_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        self.selection_model = QStandardItemModel()
        self.selection_model.setHorizontalHeaderLabels(["Directories to scan"])
        self.selection_view = QTreeView()
        self.selection_view.setModel(self.selection_model)
        self.selection_view.setHeaderHidden(False)

        self.db_label = QLabel("No database opened")
        self.scan_label = QLabel("No scan root selected")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_label = QLabel("Idle")

        self.error_label = QLabel("Errors: 0")
        self.view_errors_button = QPushButton("View Errors")
        self.view_errors_button.clicked.connect(self.show_errors)
        self.view_errors_button.setEnabled(False)

        self.open_button = QPushButton("Open DB")
        self.create_button = QPushButton("Create DB")
        self.choose_scan_button = QPushButton("Choose Scan Root")
        self.scan_button = QPushButton("Start Scanning")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.dry_run_checkbox = QCheckBox("Dry run")
        self.changed_only_checkbox = QCheckBox("Only changed files")
        self.include_root_files_checkbox = QCheckBox("Include root files")
        self.include_root_files_checkbox.setEnabled(False)
        self.report_button = QPushButton("Scan Report")
        self.report_button.setEnabled(False)
        self.refresh_button = QPushButton("Refresh Roots")
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "pending", "scanning", "done", "partial", "error"])

        self.open_button.clicked.connect(self.open_db)
        self.create_button.clicked.connect(self.create_db)
        self.choose_scan_button.clicked.connect(self.choose_scan_root)
        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.report_button.clicked.connect(self.show_scan_report)
        self.refresh_button.clicked.connect(self.refresh_roots)
        self.status_filter.currentIndexChanged.connect(self.refresh_roots)
        self.scan_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.db_label)

        db_row = QHBoxLayout()
        db_row.addWidget(self.open_button)
        db_row.addWidget(self.create_button)
        db_row.addWidget(self.refresh_button)
        db_row.addWidget(self.status_filter)
        db_row.addStretch()
        layout.addLayout(db_row)

        layout.addWidget(self.root_list)
        layout.addWidget(self.scan_label)

        scan_row = QHBoxLayout()
        scan_row.addWidget(self.choose_scan_button)
        scan_row.addWidget(self.scan_button)
        scan_row.addWidget(self.cancel_button)
        scan_row.addWidget(self.dry_run_checkbox)
        scan_row.addWidget(self.changed_only_checkbox)
        scan_row.addWidget(self.include_root_files_checkbox)
        scan_row.addWidget(self.report_button)
        scan_row.addStretch()
        layout.addLayout(scan_row)

        layout.addWidget(self.selection_view)
        layout.addWidget(self.progress)
        layout.addWidget(self.progress_label)

        error_row = QHBoxLayout()
        error_row.addWidget(self.error_label)
        error_row.addWidget(self.view_errors_button)
        error_row.addStretch()
        layout.addLayout(error_row)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.selection_model.itemChanged.connect(self.on_selection_changed)
        self.last_scan_result: Optional[ScanResult] = None
        self.last_scan_context: dict[str, str] = {}
        self.last_taken_src_dist: dict[str, int] = {}

    def open_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open SQLite DB", "", "SQLite (*.db *.sqlite)")
        if not path:
            return
        self._set_db(Path(path))

    def create_db(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Create SQLite DB", "", "SQLite (*.db *.sqlite)")
        if not path:
            return
        self._set_db(Path(path))

    def _set_db(self, path: Path) -> None:
        if self.db:
            self.db.close()
        self.db_path = path
        self.db = Database(path)
        self.db_label.setText(f"DB: {path}")
        self.scan_button.setEnabled(True)
        self.view_errors_button.setEnabled(True)
        self.report_button.setEnabled(False)
        self.refresh_roots()
        self.refresh_errors()

    def refresh_roots(self) -> None:
        self.root_list.clear()
        if not self.db:
            return
        status_filter = self.status_filter.currentText()
        for root in self.db.list_roots():
            root_item = QTreeWidgetItem([root.path, "-"])
            self.root_list.addTopLevelItem(root_item)
            for child_path, status in self.db.list_root_children_with_status(root.id):
                if status_filter != "All" and status != status_filter:
                    continue
                QTreeWidgetItem(root_item, [child_path, status])
        self.root_list.expandAll()

    def choose_scan_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Scan Root")
        if not path:
            return
        self.scan_root = Path(path)
        self.scan_label.setText(f"Scan root: {self.scan_root}")
        self.populate_discovery(self.scan_root)

    def populate_discovery(self, root: Path) -> None:
        self.selection_model.clear()
        self.selection_model.setHorizontalHeaderLabels(["Directories to scan"])

        root_item = QStandardItem(str(root))
        root_item.setCheckable(True)
        root_item.setAutoTristate(False)
        root_item.setCheckState(Qt.CheckState.Unchecked)
        root_item.setData(str(root), ROLE_PATH)
        root_item.setData(True, ROLE_IS_ROOT)
        root_has_media = self._root_has_media(root)
        root_item.setData(root_has_media, ROLE_ROOT_MEDIA)
        self.include_root_files_checkbox.setEnabled(root_has_media)
        self.include_root_files_checkbox.setChecked(False)

        for child in sorted(p for p in root.iterdir() if p.is_dir()):
            child_item = QStandardItem(child.name)
            child_item.setCheckable(True)
            child_item.setAutoTristate(False)
            child_item.setCheckState(Qt.CheckState.Unchecked)
            child_item.setData(str(child), ROLE_PATH)
            child_item.setData(False, ROLE_IS_ROOT)
            root_item.appendRow(child_item)

        self.selection_model.appendRow(root_item)
        self.selection_view.expandAll()

    def _root_has_media(self, root: Path) -> bool:
        try:
            for entry in root.iterdir():
                if entry.is_file() and (self.config.is_image(entry) or self.config.is_video(entry)):
                    return True
        except OSError:
            return False
        return False

    def on_selection_changed(self, item: QStandardItem) -> None:
        if not item:
            return

        is_root = bool(item.data(ROLE_IS_ROOT))
        if is_root:
            self._handle_root_toggle(item)
        else:
            self._handle_child_toggle(item)

    def _handle_root_toggle(self, root_item: QStandardItem) -> None:
        state = root_item.checkState()
        root_item.setData(False, ROLE_ROOT_SELF)

        self.selection_model.blockSignals(True)
        if state == Qt.CheckState.Checked:
            for i in range(root_item.rowCount()):
                child = root_item.child(i)
                child.setCheckState(Qt.CheckState.Checked)
        else:
            for i in range(root_item.rowCount()):
                child = root_item.child(i)
                child.setCheckState(Qt.CheckState.Unchecked)
        self.selection_model.blockSignals(False)

    def _handle_child_toggle(self, child_item: QStandardItem) -> None:
        root_item = child_item.parent()
        if not root_item:
            return

        child_states = [root_item.child(i).checkState() for i in range(root_item.rowCount())]
        result = compute_root_state([
            CHECKED if state == Qt.CheckState.Checked else UNCHECKED for state in child_states
        ])

        if result.all_checked:
            self.selection_model.blockSignals(True)
            root_item.setCheckState(Qt.CheckState.Checked)
            self.selection_model.blockSignals(False)
            return

        if result.any_checked:
            self.selection_model.blockSignals(True)
            root_item.setCheckState(Qt.CheckState.PartiallyChecked)
            self.selection_model.blockSignals(False)
            return

        self.selection_model.blockSignals(True)
        root_item.setCheckState(Qt.CheckState.Unchecked)
        self.selection_model.blockSignals(False)

    def _build_selections(self) -> list[DirectorySelection]:
        root_item = self.selection_model.item(0)
        if not root_item:
            return []

        root_path = Path(str(root_item.data(ROLE_PATH)))
        root_state = root_item.checkState()

        selections: list[DirectorySelection] = []

        if root_state == Qt.CheckState.Checked:
            selections.append(
                DirectorySelection(path=root_path, recursive=True, include_root_files=True)
            )
            return selections

        if self.include_root_files_checkbox.isChecked():
            selections.append(
                DirectorySelection(path=root_path, recursive=False, include_root_files=True)
            )

        for i in range(root_item.rowCount()):
            child = root_item.child(i)
            if child.checkState() == Qt.CheckState.Checked:
                selections.append(
                    DirectorySelection(
                        path=Path(str(child.data(ROLE_PATH))),
                        recursive=True,
                        include_root_files=True,
                    )
                )

        return selections

    def _resolve_errors_log_path(self) -> Optional[Path]:
        if self.config.errors_log_path:
            return Path(self.config.errors_log_path)
        if not self.db_path:
            return None
        return self.db_path.with_suffix("").with_suffix(".errors.jsonl")

    def start_scan(self) -> None:
        if not self.db_path or not self.scan_root:
            QMessageBox.warning(self, "Missing data", "Choose a DB and scan root first.")
            return

        selections = self._build_selections()
        if not selections:
            QMessageBox.warning(self, "Nothing selected", "Select at least one directory to scan.")
            return

        self.progress.setRange(0, 0)
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_label.setText("Starting scan...")

        self.worker_thread = QThread()
        self.worker = ScanWorker(
            self.db_path,
            self.config,
            self.scan_root,
            selections,
            self.dry_run_checkbox.isChecked(),
            self.changed_only_checkbox.isChecked(),
            self._resolve_errors_log_path(),
            self.db_path,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.failed.connect(self.on_scan_failed)
        self.worker.progress.connect(self.on_scan_progress)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.start()

    def cancel_scan(self) -> None:
        if hasattr(self, "worker"):
            self.worker.cancel()
            self.progress_label.setText("Cancelling...")

    def on_scan_progress(self, current: int, total: int, path: str) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        self.progress_label.setText(f"{current}/{total} {path}")

    def on_scan_finished(self, result: ScanResult) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.refresh_roots()
        self.refresh_errors()
        self.last_scan_result = result
        self.last_scan_context = {
            "root": str(self.scan_root) if self.scan_root else "",
            "dry_run": str(self.dry_run_checkbox.isChecked()),
            "changed_only": str(self.changed_only_checkbox.isChecked()),
            "include_root_files": str(self.include_root_files_checkbox.isChecked()),
        }
        if self.db and not self.dry_run_checkbox.isChecked() and self.scan_root:
            self.last_taken_src_dist = self.db.taken_src_distribution(str(self.scan_root))
        else:
            self.last_taken_src_dist = {}
        self.report_button.setEnabled(True)

        cancelled_note = "\nScan cancelled" if result.cancelled else ""
        taken_src_block = ""
        if not self.dry_run_checkbox.isChecked():
            ordered_keys = [
                "SubSecDateTimeOriginal",
                "DateTimeOriginal",
                "CreateDate",
                "XMP_CreateDate",
                "XMP_DateCreated",
                "mtime_fallback",
                "unknown",
            ]
            width = max(len(k) for k in ordered_keys)
            lines = ["", "taken_src distribution:"]
            for key in ordered_keys:
                count = self.last_taken_src_dist.get(key, 0)
                lines.append(f"  {key.ljust(width)}: {count}")
            taken_src_block = "\n".join(lines)
        QMessageBox.information(
            self,
            "Scan complete",
            f"Scanned {result.stats.directories} directories\n"
            f"Indexed {result.stats.images} images\n"
            f"Indexed {result.stats.videos} videos\n"
            f"Warnings: {result.stats.warnings}\n"
            f"Errors: {result.stats.errors}\n"
            + (
                f"See errors log: {self._resolve_errors_log_path()}\n"
                if result.stats.errors > 0
                else ""
            )
            f"Tags added: {result.stats.tags_added}\n"
            f"Tag links added: {result.stats.file_tag_links_added}\n"
            f"Category tags added: {result.stats.category_tags_added}\n"
            f"Value tags added: {result.stats.value_tags_added}"
            f"{taken_src_block}"
            f"{cancelled_note}",
        )

    def on_scan_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        QMessageBox.critical(self, "Scan failed", message)

    def show_scan_report(self) -> None:
        if not self.last_scan_result:
            QMessageBox.information(self, "Scan Report", "No scan report available yet.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Scan Report")
        layout = QVBoxLayout(dialog)

        result = self.last_scan_result
        lines = [
            f"Root: {self.last_scan_context.get('root', '')}",
            f"Dry run: {self.last_scan_context.get('dry_run', '')}",
            f"Changed only: {self.last_scan_context.get('changed_only', '')}",
            f"Include root files: {self.last_scan_context.get('include_root_files', '')}",
            f"Directories: {result.stats.directories}",
            f"Images: {result.stats.images}",
            f"Videos: {result.stats.videos}",
            f"Warnings: {result.stats.warnings}",
            f"Errors: {result.stats.errors}",
            f"Tags added: {result.stats.tags_added}",
            f"Tag links added: {result.stats.file_tag_links_added}",
            f"Category tags added: {result.stats.category_tags_added}",
            f"Value tags added: {result.stats.value_tags_added}",
        ]
        if not self.dry_run_checkbox.isChecked():
            ordered_keys = [
                "SubSecDateTimeOriginal",
                "DateTimeOriginal",
                "CreateDate",
                "XMP_CreateDate",
                "XMP_DateCreated",
                "mtime_fallback",
                "unknown",
            ]
            width = max(len(k) for k in ordered_keys)
            lines.append("taken_src distribution:")
            for key in ordered_keys:
                count = self.last_taken_src_dist.get(key, 0)
                lines.append(f"  {key.ljust(width)}: {count}")
        if result.stats.errors > 0:
            lines.append(f"See errors log: {self._resolve_errors_log_path()}")
        lines.append(f"Cancelled: {result.cancelled}")
        layout.addWidget(QLabel("\n".join(lines)))

        buttons = QDialogButtonBox()
        export_json = buttons.addButton("Export JSON", QDialogButtonBox.ButtonRole.ActionRole)
        export_csv = buttons.addButton("Export CSV", QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)

        export_json.clicked.connect(lambda: self._export_report("json"))
        export_csv.clicked.connect(lambda: self._export_report("csv"))
        close_btn.clicked.connect(dialog.close)

        dialog.exec()

    def _export_report(self, fmt: str) -> None:
        if not self.last_scan_result:
            return
        ext = "json" if fmt == "json" else "csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export Scan Report", f"scan_report.{ext}")
        if not path:
            return

        result = self.last_scan_result
        payload = {
            "root": self.last_scan_context.get("root", ""),
            "dry_run": self.last_scan_context.get("dry_run", ""),
            "changed_only": self.last_scan_context.get("changed_only", ""),
            "include_root_files": self.last_scan_context.get("include_root_files", ""),
            "directories": result.stats.directories,
            "images": result.stats.images,
            "videos": result.stats.videos,
            "warnings": result.stats.warnings,
            "errors": result.stats.errors,
            "tags_added": result.stats.tags_added,
            "file_tag_links_added": result.stats.file_tag_links_added,
            "category_tags_added": result.stats.category_tags_added,
            "value_tags_added": result.stats.value_tags_added,
            "cancelled": result.cancelled,
        }
        if not self.dry_run_checkbox.isChecked():
            payload["taken_src_distribution"] = {
                key: self.last_taken_src_dist.get(key, 0)
                for key in [
                    "SubSecDateTimeOriginal",
                    "DateTimeOriginal",
                    "CreateDate",
                    "XMP_CreateDate",
                    "XMP_DateCreated",
                    "mtime_fallback",
                    "unknown",
                ]
            }
        try:
            if fmt == "json":
                import json

                Path(path).write_text(json.dumps(payload, indent=2))
            else:
                header = ",".join(payload.keys())
                values = ",".join(str(payload[k]) for k in payload)
                Path(path).write_text(f"{header}\n{values}\n")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def refresh_errors(self) -> None:
        if not self.db:
            self.error_label.setText("Errors: 0")
            self.view_errors_button.setEnabled(False)
            return
        count = self.db.conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        self.error_label.setText(f"Errors: {count}")
        self.view_errors_button.setEnabled(count > 0)

    def show_errors(self) -> None:
        if not self.db:
            return
        errors = self.db.list_errors(50)
        if not errors:
            QMessageBox.information(self, "Errors", "No errors logged.")
            return
        text = "\n\n".join(
            f"{row['created_at']} [{row['scope']}] {row['message']}\n{row['details'] or ''}".strip()
            for row in errors
        )
        QMessageBox.information(self, "Recent Errors", text)
