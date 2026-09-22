"""Simulation lifecycle and file adapter. The results widget does not import this."""
import codecs
import json
from pathlib import Path
import time
import uuid

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .stream import JsonlReader


class RunController(QObject):
    records = Signal(list)
    log_text = Signal(str)
    notice = Signal(str)
    status_changed = Signal(str)
    run_started = Signal(str)
    finished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_log)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(lambda: self.status_changed.emit("Running"))
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)
        self.reader = None
        self.run_dir = None
        self.log_file = None
        self.cancelled = False
        self.end_status = None
        self.metadata = {}
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.log_pending = ""

    @property
    def active(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(self, case, executable, root):
        if self.active:
            raise RuntimeError("A case is already running")
        case, executable = Path(case).resolve(), Path(executable).resolve()
        if not case.is_file():
            raise ValueError("Select an existing WAM file")
        if not executable.is_file():
            raise ValueError("Select a compiled OpenWAM executable")
        self.run_dir = Path(root).expanduser().resolve() / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.run_dir.mkdir(parents=True)
        stream = self.run_dir / "results.jsonl"
        self.reader = JsonlReader(stream)
        self.log_file = (self.run_dir / "solver.log").open("wb")
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.log_pending = ""
        self.cancelled = False
        self.end_status = None
        self.metadata = {"case": str(case), "executable": str(executable), "started_unix": time.time(), "status": "running"}
        self._save_metadata()
        self.process.setWorkingDirectory(str(case.parent))
        self.run_started.emit(str(stream))
        self.status_changed.emit("Starting")
        self.process.start(str(executable), [str(case), "--output-dir", str(self.run_dir), "--results-stream", str(stream)])
        self.timer.start()

    def _save_metadata(self):
        (self.run_dir / "run.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    def stop(self):
        if not self.active:
            return
        self.cancelled = True
        self.status_changed.emit("Stopping")
        self.process.terminate()
        run_dir = self.run_dir
        QTimer.singleShot(3000, lambda: self.process.kill() if self.active and self.run_dir == run_dir else None)

    def _read_log(self):
        raw = bytes(self.process.readAllStandardOutput())
        if self.log_file:
            self.log_file.write(raw)
            self.log_file.flush()
        text = self.decoder.decode(raw)
        self.log_text.emit(text)
        parts = (self.log_pending + text).splitlines(keepends=True)
        self.log_pending = ""
        for line in parts:
            if not line.endswith(("\n", "\r")):
                self.log_pending = line
            elif "ERROR" in line.upper() or "WARNING" in line.upper():
                self.notice.emit(line.strip())

    def poll(self):
        if self.reader is None:
            return
        try:
            records = self.reader.read_available()
            if records:
                for record in records:
                    if record["type"] == "end":
                        self.end_status = record["status"]
                        if record.get("message"):
                            self.notice.emit(record["message"])
                self.records.emit(records)
        except (ValueError, OSError) as error:
            self.notice.emit("Live results unavailable: " + str(error))
            self.reader = None  # A consumer failure never stops the solver.

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.notice.emit(self.process.errorString())
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _finished(self, code, exit_status):
        self.timer.stop()
        self._read_log()
        while self.reader:
            previous = self.reader.offset
            self.poll()
            if self.reader is None or self.reader.offset == previous:
                break
        if self.log_pending and any(k in self.log_pending.upper() for k in ("ERROR", "WARNING")):
            self.notice.emit(self.log_pending)
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        if self.cancelled:
            status = "cancelled"
        elif code == 0 and exit_status == QProcess.ExitStatus.NormalExit and self.end_status == "completed":
            status = "completed"
        else:
            status = "failed"
            self.notice.emit(f"Solver stopped with exit code {code}. Partial results are retained; see the log.")
        self.metadata.update(status=status, exit_code=code, finished_unix=time.time())
        self._save_metadata()
        self.status_changed.emit(status.capitalize())
        self.finished.emit(status)
