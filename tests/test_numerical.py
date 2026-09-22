"""Optional C++ regression: OPENWAM_BUILD_DIR=build-debug python -m unittest ..."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("OPENWAM_BUILD_DIR"), "Set OPENWAM_BUILD_DIR to test compiled solver averages")
class NumericalTests(unittest.TestCase):
    def test_unequal_intervals_and_snapshot_readers(self):
        build = Path(os.environ["OPENWAM_BUILD_DIR"]).resolve()
        flags = (build / "Source/Turbocompressor/CMakeFiles/Turbocompressor.dir/flags.make").read_text()
        includes = next(line.split("=", 1)[1] for line in flags.splitlines() if line.startswith("CXX_INCLUDES ="))
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "numerical"
            command = ["c++", "-std=c++11", *shlex.split(includes), str(Path(__file__).with_name("numerical.cpp")),
                       "-Wl,--start-group", *map(str, sorted((build / "lib").glob("*.a"))), "-Wl,--end-group", "-o", str(exe)]
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run([str(exe), str(Path(directory) / "shaft.dat")], check=True)
