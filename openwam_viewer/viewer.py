"""Embeddable results widget: feed descriptors and samples; no process/file knowledge."""
import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHeaderView,
                             QHBoxLayout, QLabel, QPushButton, QSplitter, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from .model import ResultsModel

COLORS = ["#38d9c5", "#72a9ff", "#ffce73", "#ee8bb7", "#b1a0ff", "#93d982"]


class PlotPanel(QWidget):
    selection_requested = Signal(object)

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.keys = []
        self.curves = []
        self.previous_curves = []
        self.model = None
        self._render_state = None
        self._axis_label = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"PLOT {index}"))
        self.axis = QComboBox()
        self.axis.addItems(["Cycle", "Time"])
        self.overlay = QCheckBox("Previous cycle")
        self.overlay.setChecked(True)
        self.overlay.setVisible(False)
        add = QPushButton("Plot selection")
        add.clicked.connect(lambda: self.selection_requested.emit(self))
        row.addWidget(self.axis)
        row.addWidget(self.overlay)
        row.addStretch()
        row.addWidget(add)
        layout.addLayout(row)
        self.plot = pg.PlotWidget(background="#111c2b")
        self.plot.showGrid(x=True, y=True, alpha=.16)
        # Preserve the engineering units declared by the solver (no kdegC or krpm).
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.addLegend(offset=(10, 10))
        self.plot.setMinimumSize(260, 200)
        self.plot.setLabel("bottom", "Cycle")
        layout.addWidget(self.plot, 1)
        self.latest = QLabel("Choose variables in the browser, then Plot selection")
        self.latest.setWordWrap(True)
        self.cursor_text = QLabel("Move over a curve to inspect values")
        layout.addWidget(self.latest)
        layout.addWidget(self.cursor_text)
        self.crosshair = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#6a7b91", style=Qt.PenStyle.DotLine))
        self.plot.addItem(self.crosshair, ignoreBounds=True)
        self.proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=20, slot=self._mouse)
        self.axis.currentTextChanged.connect(lambda: self.render())
        self.overlay.toggled.connect(lambda: self.render())

    def configure(self, keys, model):
        self.model = model
        self.keys = keys
        self._render_state = None
        for curve in self.curves + self.previous_curves:
            self.plot.removeItem(curve)
        self.plot.plotItem.legend.clear()
        self.curves, self.previous_curves = [], []
        channel = model.channels[keys[0]]
        trace = channel.kind == "trace"
        self.axis.blockSignals(True)
        self.axis.clear()
        self.axis.addItems(["Cylinder angle", "Engine angle"] if trace else ["Cycle", "Time"])
        self.axis.blockSignals(False)
        self.overlay.setVisible(trace)
        self.plot.setLabel("left", channel.label if len(keys) == 1 else "Value", units=channel.unit if channel.unit != "1" else None)
        for i, key in enumerate(keys):
            desc = model.channels[key]
            color = COLORS[i % len(COLORS)]
            self.curves.append(self.plot.plot([], [], name=f"{desc.component} · {desc.label}",
                                              pen=pg.mkPen(color, width=2), connect="finite",
                                              symbol=None if trace else "o", symbolSize=5,
                                              symbolBrush=color, symbolPen=None))
            self.previous_curves.append(self.plot.plot([], [], pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine), connect="finite"))
        self.plot.enableAutoRange()
        self.render()

    def render(self):
        if not self.keys or self.model is None:
            return
        axis = self.axis.currentText()
        state = (axis, self.overlay.isChecked(), tuple(id(self.model.latest.get(key)) for key in self.keys))
        if state == self._render_state:
            return
        self._render_state = state
        unit = self.model.channels[self.keys[0]].unit
        bottom = {"Time": ("Simulation time", "s"), "Cycle": ("Engine cycle", None),
                  "Cylinder angle": ("Cylinder-local crank angle", "deg"),
                  "Engine angle": ("Engine-reference crank angle", "deg")}[axis]
        if bottom != self._axis_label:
            self.plot.setLabel("bottom", bottom[0], units=bottom[1])
            self._axis_label = bottom
        labels = []
        for i, key in enumerate(self.keys):
            x, y = self.model.series(key, axis)
            self.curves[i].setData(np.asarray(x), np.asarray(y))
            previous = self.overlay.isVisible() and self.overlay.isChecked()
            px, py = self.model.series(key, axis, previous=True) if previous else ([], [])
            self.previous_curves[i].setData(np.asarray(px), np.asarray(py))
            point = self.model.latest.get(key)
            if point:
                value = f"{point.value:,.8g} {unit}" if math.isfinite(point.value) else "Unavailable"
                labels.append(f"{self.model.channels[key].component}: {value}" + (" (partial interval)" if point.partial else ""))
        self.latest.setText("  •  ".join(labels) or "Waiting for the first sample")

    def _mouse(self, event):
        if not self.keys or self.model is None:
            return
        pos = event[0]
        if not self.plot.sceneBoundingRect().contains(pos):
            return
        x_pos = self.plot.plotItem.vb.mapSceneToView(pos).x()
        self.crosshair.setPos(x_pos)
        x, y = self.model.series(self.keys[0], self.axis.currentText())
        if not x:
            return
        i = int(np.argmin(np.abs(np.asarray(x) - x_pos)))
        desc = self.model.channels[self.keys[0]]
        self.cursor_text.setText(f"{desc.component}  ·  x {x[i]:.4g}  ·  {y[i]:.6g} {desc.unit}")


class ResultsViewer(QWidget):
    """Public API: clear(), add_channels(), add_sample(), refresh()."""
    notice = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = ResultsModel()
        self.dirty = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter()
        layout.addWidget(splitter)
        self.browser = QTreeWidget()
        self.browser.setHeaderLabels(["Results", "Unit"])
        self.browser.header().setStretchLastSection(False)
        self.browser.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.browser.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.browser.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.browser.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.browser.setMinimumWidth(230)
        self.browser.setMaximumWidth(440)
        splitter.addWidget(self.browser)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        self.panels = [PlotPanel(i + 1) for i in range(4)]
        for i, panel in enumerate(self.panels):
            grid.addWidget(panel, i // 2, i % 2)
            panel.selection_requested.connect(self.plot_selection)
        splitter.addWidget(grid_widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([290, 1050])
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def clear(self):
        self.model = ResultsModel()
        self.browser.clear()
        for panel in self.panels:
            panel.keys = []
            panel.model = self.model
            for curve in panel.curves + panel.previous_curves:
                curve.setData([], [])
            panel.plot.plotItem.legend.clear()
            panel.latest.setText("Waiting for results")
            panel.cursor_text.setText("")

    def add_channels(self, channels, cycle_degrees=720.):
        self.model.add_channels(channels, cycle_degrees)
        self.browser.clear()
        groups = {}
        for key, channel in self.model.channels.items():
            if channel.component not in groups:
                title = channel.component.replace(".", " ").title()
                groups[channel.component] = QTreeWidgetItem(self.browser, [title])
            item = QTreeWidgetItem(groups[channel.component], [channel.label, channel.unit])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setToolTip(0, f"{key}\n{channel.kind}")
        self.browser.expandToDepth(0)
        defaults = [["engine.1.power_cycle"], [key for key in self.model.channels if key.startswith("shaft.")],
                    ["cylinder.1.pressure"], ["cylinder.1.temperature"]]
        for panel, keys in zip(self.panels, defaults):
            keys = [key for key in keys if key in self.model.channels]
            if keys:
                panel.configure(keys, self.model)

    def add_sample(self, sample):
        self.model.add_sample(sample)
        self.dirty = True

    def accept(self, record):
        if record["type"] == "channels":
            self.add_channels(record["channels"], record.get("cycle_degrees", 720.))
        elif record["type"] == "sample":
            self.add_sample(record)
        else:
            self.model.accept(record)

    def plot_selection(self, panel):
        keys = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.browser.selectedItems()]
        keys = [key for key in keys if key is not None]
        if not keys:
            self.notice.emit("Select one or more variables in the results browser first.")
            return
        first = self.model.channels[keys[0]]
        if any((self.model.channels[k].unit, self.model.channels[k].kind) != (first.unit, first.kind) for k in keys):
            self.notice.emit("Overlay variables with the same units and sampling type. Use separate panels for other quantities.")
            return
        panel.configure(keys, self.model)

    def refresh(self):
        if self.dirty:
            for panel in self.panels:
                panel.render()
            self.dirty = False

    def plotted_channels(self):
        return set(key for panel in self.panels for key in panel.keys)
