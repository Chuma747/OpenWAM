"""Version 1 result stream adapter; independent of the plotting toolkit."""
import csv
import json
from pathlib import Path


class JsonlReader:
    """Read only complete records, even when a producer is halfway through writing."""

    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.pending = b""
        self.identity = None
        self.generation = 0

    def read_available(self, max_bytes=1024 * 1024):
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return []
        identity = (stat.st_dev, stat.st_ino)
        if self.identity is not None and (identity != self.identity or stat.st_size < self.offset):
            self.offset = 0
            self.pending = b""
            self.generation += 1
        self.identity = identity
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(max_bytes)
        self.offset += len(data)
        parts = (self.pending + data).split(b"\n")
        self.pending = parts.pop()
        if len(self.pending) > 8 * 1024 * 1024:
            raise ValueError("Result record exceeds 8 MiB")
        records = []
        for line in parts:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict) or "type" not in record:
                raise ValueError("Invalid result record")
            if record["type"] == "run" and record.get("schema_version") != 1:
                raise ValueError("Unsupported result stream version")
            records.append(record)
        return records


def export_csv(stream_path, destination, selected):
    """Export full recorded history, not just the cycles retained by the widget."""
    selected = set(selected)
    channels = {}
    count = 0
    with Path(stream_path).open("rb") as source, Path(destination).open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["time_s", "cycle", "engine_angle_deg", "cylinder_angle_deg", "kind",
                         "channel", "label", "unit", "value", "partial_interval"])
        for line in source:
            if not line.endswith(b"\n"):
                break
            record = json.loads(line)
            if record["type"] == "channels":
                channels.update((c["id"], c) for c in record["channels"])
            if record["type"] != "sample":
                continue
            for key, value in record["values"].items():
                if key not in selected or key not in channels:
                    continue
                channel = channels[key]
                writer.writerow([record["time"], record["cycle"], record.get("angle", ""),
                                 record.get("local_angles", {}).get(channel["component"], ""),
                                 record["kind"], key, channel["label"], channel["unit"],
                                 "" if value is None else value, record.get("partial", False)])
                count += 1
    return count
