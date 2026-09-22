"""In-memory results, usable with live, replay, in-process or network adapters."""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Channel:
    id: str
    component: str
    label: str
    unit: str
    kind: str


@dataclass(frozen=True)
class Point:
    time: float
    cycle: int
    angle: float
    value: float
    local_angle: float
    partial: bool = False


class ResultsModel:
    def __init__(self):
        self.channels = {}
        self.averages = defaultdict(list)
        self.traces = defaultdict(OrderedDict)
        self.local_traces = defaultdict(OrderedDict)
        self.local_cycles = defaultdict(int)
        self.last_local_angle = {}
        self.latest = {}
        self.run = {}
        self.progress = 0.0
        self.cycle_degrees = 720.0
        self.status = "Waiting for results"

    def add_channels(self, channels, cycle_degrees=720.0):
        self.cycle_degrees = cycle_degrees
        for item in channels:
            channel = item if isinstance(item, Channel) else Channel(**{k: item[k] for k in Channel.__dataclass_fields__})
            self.channels[channel.id] = channel

    def add_sample(self, record):
        if "progress" in record:
            self.progress = max(0., min(100., float(record["progress"])))
        for owner, angle in record.get("local_angles", {}).items():
            if angle is None:
                continue
            if angle < self.last_local_angle.get(owner, angle) - self.cycle_degrees / 2:
                self.local_cycles[owner] += 1
            self.last_local_angle[owner] = angle
        for key, value in record["values"].items():
            channel = self.channels.get(key)
            if channel is None:
                continue
            value = float(value) if value is not None else math.nan
            if not math.isfinite(value):
                value = math.nan
            local_angle = record.get("local_angles", {}).get(channel.component)
            point = Point(float(record["time"]), int(record["cycle"]),
                          float(record.get("angle", math.nan)), value,
                          float(local_angle) if local_angle is not None else math.nan,
                          bool(record.get("partial", False)))
            self.latest[key] = point
            if channel.kind == "average":
                self.averages[key].append(point)
            else:
                for store, cycle in ((self.traces[key], point.cycle),
                                     (self.local_traces[key], self.local_cycles[channel.component])):
                    store.setdefault(cycle, []).append(point)
                    while len(store) > 2:
                        store.popitem(last=False)

    def accept(self, record):
        kind = record["type"]
        if kind == "run":
            if record.get("schema_version") != 1:
                raise ValueError("Unsupported result stream version")
            self.run = record
            self.status = "Running"
        elif kind == "channels":
            self.add_channels(record["channels"], record.get("cycle_degrees", 720.))
        elif kind == "sample":
            self.add_sample(record)
        elif kind == "end":
            self.status = record["status"].capitalize()
            if record["status"] == "completed":
                self.progress = 100.

    def series(self, key, axis="Cycle", previous=False):
        channel = self.channels[key]
        if channel.kind == "average":
            points = self.averages[key]
            x = [p.time if axis == "Time" else p.cycle for p in points]
        else:
            store = self.local_traces[key] if axis == "Cylinder angle" else self.traces[key]
            groups = list(store.values())
            if not groups or (previous and len(groups) < 2):
                return [], []
            points = groups[-2 if previous else -1]
            x = [p.local_angle if axis == "Cylinder angle" else p.angle for p in points]
        return x, [p.value for p in points]
