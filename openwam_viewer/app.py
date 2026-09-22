"""Small desktop host for the reusable results widget."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
                             QVBoxLayout, QWidget)

from .controller import RunController
from .stream import JsonlReader, export_csv
from .viewer import ResultsViewer

STYLE = """
QWidget { background: #0d1623; color: #dbe6f3; font-size: 12px; }
QLineEdit, QComboBox, QTreeWidget, QPlainTextEdit { background: #142235; border: 1px solid #293b51; border-radius: 4px; padding: 5px; }
QPushButton { background: #22354d; border: 1px solid #354b65; padding: 7px 12px; border-radius: 4px; }
QPushButton:hover { background: #304962; }
QPushButton:disabled { color: #607188; background: #162233; }
QPushButton#run { color: #081d21; background: #38d9c5; font-weight: bold; }
QHeaderView::section { background: #1b2c42; border: none; padding: 6px; }
QTreeWidget::item:selected { background: #29516b; }
QProgressBar { border: 1px solid #293b51; border-radius: 4px; text-align: center; background: #142235; }
QProgressBar::chunk { background: #247e79; }
QSplitter::handle { background: #25374d; }
"""


class MainWindow(QMainWindow):
    def __init__(self, case="", executable="", runs_dir="runs"):
        super().__init__()
        self.setWindowTitle("OpenWAM · Live results")
        self.resize(1450, 950)
        self.runs_dir = Path(runs_dir).resolve()
        self.stream_path = None
        self.replay = None
        self.started = None
        self.elapsed = 0.
        self.closing = False
        self.controller = RunController(self)
        self.controller.records.connect(self._records)
        self.controller.log_text.connect(self._log)
        self.controller.notice.connect(self._notice)
        self.controller.status_changed.connect(self._status)
        self.controller.run_started.connect(self._new_run)
        self.controller.finished.connect(self._finished)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("OPENWAM   /   LIVE RESULTS")
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding: 8px 0;")
        layout.addWidget(title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Case"))
        self.case = QLineEdit(case)
        self.case.setPlaceholderText("Select a WAM case")
        row.addWidget(self.case, 1)
        self.browse = QPushButton("Open case…")
        self.browse.clicked.connect(self._choose_case)
        row.addWidget(self.browse)
        self.run = QPushButton("▶  Run")
        self.run.setObjectName("run")
        self.run.clicked.connect(self._run)
        row.addWidget(self.run)
        self.stop = QPushButton("■  Stop")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.controller.stop)
        row.addWidget(self.stop)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Solver"))
        self.executable = QLineEdit(executable)
        self.executable.setPlaceholderText("Path to the compiled OpenWAM executable")
        row.addWidget(self.executable, 1)
        self.choose_solver = QPushButton("Choose…")
        self.choose_solver.clicked.connect(self._choose_solver)
        row.addWidget(self.choose_solver)
        self.open_results = QPushButton("Open saved run…")
        self.open_results.clicked.connect(self._choose_results)
        row.addWidget(self.open_results)
        self.export = QPushButton("Export plotted data…")
        self.export.clicked.connect(self._export)
        row.addWidget(self.export)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setMinimumWidth(150)
        row.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("%p%")
        row.addWidget(self.progress, 1)
        self.clock = QLabel("Elapsed 00:00:00")
        row.addWidget(self.clock)
        layout.addLayout(row)
        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("color: #ffce73; padding: 4px;")
        self.notice.hide()
        layout.addWidget(self.notice)
        self.viewer = ResultsViewer()
        self.viewer.notice.connect(self._notice)
        layout.addWidget(self.viewer, 1)
        self.log_toggle = QPushButton("▸  Details and solver log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        layout.addWidget(self.log_toggle)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(180)
        self.log.hide()
        layout.addWidget(self.log)
        self.tick = QTimer(self)
        self.tick.setInterval(200)
        self.tick.timeout.connect(self._tick)
        self.tick.start()
        self.replay_timer = QTimer(self)
        self.replay_timer.setInterval(0)
        self.replay_timer.timeout.connect(self._replay_chunk)

    def _choose_case(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open case", self.case.text(), "OpenWAM cases (*.WAM *.wam)")
        if path:
            self.case.setText(path)

    def _choose_solver(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select OpenWAM executable", self.executable.text())
        if path:
            self.executable.setText(path)

    def _run(self):
        try:
            self.replay_timer.stop()
            self.controller.start(self.case.text(), self.executable.text(), self.runs_dir)
        except (ValueError, RuntimeError, OSError) as error:
            self._notice(str(error))
            self._enable_controls(True)

    def _enable_controls(self, enabled):
        for widget in (self.run, self.case, self.executable, self.browse, self.choose_solver, self.open_results):
            widget.setEnabled(enabled)
        self.stop.setEnabled(not enabled and self.controller.active)

    def _new_run(self, path):
        self.stream_path = Path(path)
        self.viewer.clear()
        self.log.clear()
        self.notice.hide()
        self.started = time.monotonic()
        self.elapsed = 0.
        self.progress.setValue(0)
        self._enable_controls(False)
        self.stop.setEnabled(True)
        self.log.setToolTip(str(self.stream_path.parent / "solver.log"))

    def _records(self, records):
        try:
            for record in records:
                self.viewer.accept(record)
        except (ValueError, KeyError, TypeError) as error:
            self._notice("Cannot display result: " + str(error))

    def _log(self, text):
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)

    def _notice(self, message):
        self.notice.setText(message)
        self.notice.show()

    def _status(self, status):
        self.status.setText(status)

    def _finished(self, status):
        self.elapsed = time.monotonic() - self.started if self.started is not None else 0.
        self.started = None
        self.viewer.model.status = status.capitalize()
        self.viewer.refresh()
        self._enable_controls(True)
        if self.closing:
            self.close()

    def _tick(self):
        elapsed = time.monotonic() - self.started if self.started is not None else self.elapsed
        self.clock.setText(f"Elapsed {int(elapsed)//3600:02}:{int(elapsed)//60%60:02}:{int(elapsed)%60:02}")
        self.progress.setValue(round(self.viewer.model.progress * 10))

    def _toggle_log(self, checked):
        self.log.setVisible(checked)
        self.log_toggle.setText(("▾" if checked else "▸") + "  Details and solver log")

    def _choose_results(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open saved results", str(self.runs_dir), "Result streams (*.jsonl)")
        if path:
            self.load_run(path)

    def load_run(self, path):
        if self.controller.active:
            raise RuntimeError("Finish the active case before opening saved results")
        self.stream_path = Path(path)
        self.viewer.clear()
        self.log.clear()
        self.notice.hide()
        self.elapsed = 0.
        self.replay = JsonlReader(path)
        self.status.setText("Loading saved run")
        self._enable_controls(False)
        self.stop.setEnabled(False)
        log_path = self.stream_path.parent / "solver.log"
        if log_path.exists():
            with log_path.open("rb") as stream:
                stream.seek(max(0, log_path.stat().st_size - 100_000))
                self.log.setPlainText(stream.read().decode("utf-8", errors="replace"))
        self.replay_timer.start()

    def _replay_chunk(self):
        try:
            before = self.replay.offset
            self._records(self.replay.read_available())
            if self.replay.offset != before:
                return
            self.replay_timer.stop()
            status = self.viewer.model.status
            metadata_path = self.stream_path.parent / "run.json"
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text())
                status = metadata.get("status", status).capitalize()
                self.elapsed = max(0., metadata.get("finished_unix", metadata["started_unix"]) - metadata["started_unix"])
            if status in ("Running", "Waiting for results"):
                status = "Incomplete / interrupted"
            self.status.setText(status + " · saved run")
            self.viewer.refresh()
            self._enable_controls(True)
        except (OSError, ValueError, KeyError) as error:
            self.replay_timer.stop()
            self._notice("Cannot load results: " + str(error))
            self._enable_controls(True)

    def _export(self):
        if self.stream_path is None or not self.viewer.plotted_channels():
            self._notice("Plot at least one result before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export plotted channels", "results.csv", "CSV files (*.csv)")
        if path:
            try:
                count = export_csv(self.stream_path, path, self.viewer.plotted_channels())
                self._notice(f"Exported {count:,} values from the full recorded history.")
            except (OSError, ValueError) as error:
                self._notice("Export failed: " + str(error))

    def closeEvent(self, event):
        if self.controller.active:
            self.closing = True
            self.controller.stop()
            event.ignore()
        else:
            event.accept()


def main():
    root = Path(__file__).resolve().parent.parent
    if not (root / "Source").is_dir():
        root = Path.cwd()
    candidates = [root / "build-live/bin/release/OpenWAM", root / "build-debug/bin/debug/OpenWAM", root / "build/bin/release/OpenWAM"]
    solver = next((str(p) for p in candidates if p.is_file()), shutil.which("OpenWAM") or "")
    parser = argparse.ArgumentParser(description="Run OpenWAM cases with live desktop plots")
    parser.add_argument("--case", default="")
    parser.add_argument("--executable", default=solver)
    parser.add_argument("--runs-dir", default=str(root / "runs"))
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyleSheet(STYLE)
    window = MainWindow(args.case, args.executable, args.runs_dir)
    window.show()
    sys.exit(app.exec())
