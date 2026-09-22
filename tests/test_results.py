import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from openwam_viewer.model import ResultsModel
from openwam_viewer.stream import JsonlReader, export_csv


CHANNELS = [dict(id="engine.1.power", component="engine.1", label="Power", unit="kW", kind="average"),
            dict(id="cylinder.1.pressure", component="cylinder.1", label="Pressure", unit="bar", kind="trace")]


def sample(cycle, angle, local, value=2):
    return dict(type="sample", kind="trace", time=cycle + angle / 720, cycle=cycle, angle=angle,
                local_angles={"cylinder.1": local}, values={"cylinder.1.pressure": value})


class ResultsTests(unittest.TestCase):
    def test_two_cycles_and_independent_local_wrap(self):
        model = ResultsModel()
        model.add_channels(CHANNELS)
        for record in [sample(0, 600, 100), sample(1, 0, 220), sample(1, 400, 620),
                       sample(1, 600, 100), sample(2, 0, 220), sample(2, 400, 620), sample(2, 600, 100)]:
            model.add_sample(record)
        self.assertEqual(list(model.traces["cylinder.1.pressure"]), [1, 2])
        self.assertEqual(len(model.local_traces["cylinder.1.pressure"]), 2)
        self.assertEqual(model.series("cylinder.1.pressure", "Cylinder angle")[0], [100])
        self.assertEqual(model.series("cylinder.1.pressure", "Cylinder angle", True)[0], [100, 220, 620])

    def test_average_history_and_missing_values(self):
        model = ResultsModel()
        model.add_channels(CHANNELS)
        for cycle in range(20):
            model.add_sample(dict(type="sample", kind="average", cycle=cycle, time=cycle / 10,
                                  values={"engine.1.power": None if cycle == 4 else cycle}))
        x, y = model.series("engine.1.power", "Time")
        self.assertEqual(len(x), 20)
        self.assertEqual(x[-1], 1.9)
        self.assertTrue(math.isnan(y[4]))

    def test_partial_records_and_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            reader = JsonlReader(path)
            self.assertEqual(reader.read_available(), [])
            line = json.dumps(dict(type="run", schema_version=1, input="tést.WAM"), ensure_ascii=False).encode() + b"\n"
            split = line.index("é".encode()) + 1
            path.write_bytes(line[:split])
            self.assertEqual(reader.read_available(), [])
            with path.open("ab") as stream:
                stream.write(line[split:])
            self.assertEqual(reader.read_available()[0]["input"], "tést.WAM")
            self.assertEqual(reader.read_available(), [])
            path.write_text('{"type":"end","status":"completed"}\n')
            self.assertEqual(reader.read_available()[0]["type"], "end")
            self.assertEqual(reader.generation, 1)

    def test_invalid_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_text('{"type":"run","schema_version":99}\n')
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                JsonlReader(path).read_available()

    def test_export_uses_full_history_and_ignores_partial_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "results.jsonl", Path(directory) / "export.csv"
            records = [dict(type="channels", channels=CHANNELS)] + [sample(i, 10, 40) for i in range(10)]
            path.write_text("".join(json.dumps(r) + "\n" for r in records) + '{"type":"sample"')
            self.assertEqual(export_csv(path, output, ["cylinder.1.pressure"]), 10)
            with output.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[-1]["cycle"], "9")
            self.assertEqual(rows[-1]["cylinder_angle_deg"], "40")


if __name__ == "__main__":
    unittest.main()
