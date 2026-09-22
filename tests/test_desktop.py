"""Run with QT_QPA_PLATFORM=offscreen for headless validation."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from PySide6.QtWidgets import QApplication

from openwam_viewer.app import MainWindow, STYLE
from openwam_viewer.controller import RunController
from openwam_viewer.viewer import ResultsViewer


APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.01)
    if not predicate():
        raise AssertionError("Timed out waiting for Qt event")


class DesktopTests(unittest.TestCase):
    def test_embedded_viewer_without_process(self):
        viewer = ResultsViewer()
        viewer.add_channels([dict(id="engine.1.power_cycle", component="engine.1", label="Power", unit="kW", kind="average")])
        viewer.add_sample(dict(type="sample", kind="average", time=.1, cycle=1, values={"engine.1.power_cycle": 123}))
        viewer.refresh()
        self.assertEqual(viewer.panels[0].curves[0].getData()[1].tolist(), [123])
        viewer.clear()
        self.assertFalse(viewer.model.channels)
        viewer.close()

    def test_controller_completion_restart_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / "case.WAM"
            case.write_text("fixture")
            fake = root / "solver"
            fake.write_text('''#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
stream = Path(sys.argv[sys.argv.index('--results-stream') + 1])
with stream.open('w') as f:
    f.write(json.dumps(dict(type='run', schema_version=1)) + '\\n'); f.flush()
    print('WARNING: fixture warning', flush=True)
    time.sleep(.4)
    f.write(json.dumps(dict(type='end', status='completed')) + '\\n'); f.flush()
''')
            fake.chmod(0o755)
            controller = RunController()
            finished, notices, records = [], [], []
            controller.finished.connect(finished.append)
            controller.notice.connect(notices.append)
            controller.records.connect(records.extend)
            controller.start(case, fake, root / "runs")
            first = controller.run_dir
            until(lambda: len(finished) == 1)
            self.assertEqual(finished[-1], "completed")
            self.assertTrue(any("fixture warning" in notice for notice in notices))
            self.assertEqual(records[-1]["type"], "end")
            controller.start(case, fake, root / "runs")
            self.assertNotEqual(first, controller.run_dir)
            until(lambda: controller.process.processId() > 0)
            controller.stop()
            until(lambda: len(finished) == 2)
            self.assertEqual(finished[-1], "cancelled")
            self.assertEqual(json.loads((controller.run_dir / "run.json").read_text())["status"], "cancelled")
            fake.write_text('#!/bin/sh\necho "ERROR: fixture failure"\nexit 2\n')
            controller.start(case, fake, root / "runs")
            until(lambda: len(finished) == 3)
            self.assertEqual(finished[-1], "failed")

    def test_reopen_interrupted_run(self):
        with tempfile.TemporaryDirectory() as directory:
            stream = Path(directory) / "results.jsonl"
            stream.write_text('{"type":"run","schema_version":1}\n')
            window = MainWindow(runs_dir=directory)
            window.load_run(stream)
            until(lambda: not window.replay_timer.isActive())
            self.assertIn("Incomplete", window.status.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
