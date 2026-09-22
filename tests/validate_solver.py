"""Opt-in real-case validation and paired overhead measurement.

python tests/validate_solver.py --executable build-live/bin/release/OpenWAM \
    --case 'input/4VPA6B 2.WAM' --output /tmp/openwam-comparison
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import time


def replace_block(data, tag, owner, body):
    pattern = rb"(<" + tag.encode() + rb" id='" + owner.encode() + rb"'>).*?(</" + tag.encode() + rb">)"
    result, count = re.subn(pattern, lambda m: m[1] + b"\r\n" + body.encode() + b"\r\n" + m[2], data, flags=re.S)
    if count != 1:
        raise ValueError(f"Expected one {tag}/{owner} block")
    return result


def numeric_dat(path):
    lines = path.read_text(errors="replace").splitlines()
    return [list(map(float, row.split())) for row in lines[1:] if row.strip()]


def compare(a, b):
    assert len(a) == len(b), (len(a), len(b))
    for left, right in zip(a, b):
        assert len(left) == len(right)
        for x, y in zip(left, right):
            assert math.isfinite(x) and math.isfinite(y), (x, y)
            assert math.isclose(x, y, rel_tol=1e-10, abs_tol=1e-12), (x, y)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--viewer", action="store_true", help="Include the visible four-panel viewer in monitored timings")
    args = parser.parse_args()
    exe, original, root = Path(args.executable).resolve(), Path(args.case).resolve(), Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = original.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    # Seven absolute engine cycles include six full periods after this case's 621° start.
    source, n = re.subn(rb"(<BLOQUE_I[^>]*>\s*\S+\s+\S+\s+)\S+", rb"\g<1>7.000000e+00", source, count=1)
    assert n == 1
    source = replace_block(source, "RESULTADOS_MEDIOS", "EN_MOTOR", "1\r\n10 0 1 2 7 9 12 13 15 17 22")
    source = replace_block(source, "RESULTADOS_MEDIOS", "EN_TURBOGRUPOS", "2\r\n1 1 0\r\n2 1 0")
    source = replace_block(source, "RESULTADOS_INSTANTANEOS", "EN_CILINDROS", "4\r\n1 2 0 1\r\n2 2 0 1\r\n3 2 0 1\r\n4 2 0 1")
    source, n = re.subn(rb"(<BLOQUE_X[^>]*>\s*)\d+", rb"\g<1>2", source, count=1)
    assert n == 1
    case = root / "case.WAM"
    case.write_bytes(source)
    times = {False: [], True: []}
    last = {}
    if args.viewer:
        from PySide6.QtWidgets import QApplication
        from openwam_viewer.viewer import ResultsViewer
        from openwam_viewer.stream import JsonlReader
        app = QApplication([])
        viewer = ResultsViewer()
        viewer.resize(1450, 900)
        viewer.show()
        app.processEvents()
    for pair in range(args.pairs):
        for monitored in ([False, True] if pair % 2 == 0 else [True, False]):
            output = root / f"pair-{pair}-{'live' if monitored else 'plain'}"
            output.mkdir()
            command = [str(exe), str(case), "--output-dir", str(output)]
            if monitored:
                command += ["--results-stream", str(output / "results.jsonl")]
            start = time.perf_counter()
            with (output / "solver.log").open("wb") as log:
                if args.viewer and monitored:
                    viewer.clear()
                    reader = JsonlReader(output / "results.jsonl")
                    with subprocess.Popen(command, cwd=original.parent, stdout=log, stderr=subprocess.STDOUT) as process:
                        next_refresh = start
                        while process.poll() is None:
                            now = time.perf_counter()
                            if now - start > 1200:
                                process.kill()
                                raise TimeoutError("Solver validation timed out")
                            if now >= next_refresh:
                                for record in reader.read_available():
                                    viewer.accept(record)
                                viewer.refresh()
                                app.processEvents()
                                next_refresh = now + .2
                            time.sleep(.005)
                        assert process.returncode == 0, process.returncode
                else:
                    subprocess.run(command, cwd=original.parent, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
            times[monitored].append(time.perf_counter() - start)
            last[monitored] = output
        compare(numeric_dat(last[False] / "caseAVG.DAT"), numeric_dat(last[True] / "caseAVG.DAT"))
        compare(numeric_dat(last[False] / "caseINS.DAT"), numeric_dat(last[True] / "caseINS.DAT"))
        print(f"Pair {pair + 1}: solver histories match", flush=True)
    records = [json.loads(line) for line in (last[True] / "results.jsonl").read_text().splitlines()]
    assert records[-1]["type"] == "end" and records[-1]["status"] == "completed"
    averages = [r for r in records if r.get("kind") == "average"]
    assert len(averages) >= 6
    assert averages[-1]["interval_angle_end"] > 2880
    assert averages[0]["values"]["shaft.1.rpm"] == 45000 or math.isclose(averages[0]["values"]["shaft.1.rpm"], 45000, rel_tol=1e-10)
    assert averages[-1]["values"]["shaft.1.rpm"] != averages[0]["values"]["shaft.1.rpm"]
    for row, record in zip(numeric_dat(last[True] / "caseAVG.DAT"), averages):
        # DAT text uses lower precision than the live stream.
        for index, key in [(7, "engine.1.power"), (8, "engine.1.power_cycle"), (10, "engine.1.rpm"), (12, "shaft.1.rpm")]:
            assert math.isclose(row[index], record["values"][key], rel_tol=1e-5, abs_tol=1e-6), (key, row[index], record["values"][key])
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    overhead = 100 * (statistics.median(times[True]) / statistics.median(times[False]) - 1)
    report = {"plain_seconds": times[False], "live_seconds": times[True], "median_overhead_percent": overhead,
              "averages": len(averages), "histories_match": True, "original_unchanged": True,
              "includes_viewer": args.viewer}
    (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
