# OpenWAM live results

A Linux desktop application for running WAM cases and watching results develop. The
solver remains a standalone C++ executable; the Python results widget is reusable.

## Build and start

```bash
cmake -S . -B build-live -DCMAKE_BUILD_TYPE=Release
cmake --build build-live --parallel 2
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/openwam-live
```

Use **Open case…**, select your WAM input, then **Run**. The default executable is
the Release build above, falling back to `build-debug/bin/debug/OpenWAM` if present.
You can select another freshly built executable in the window. A Qt-capable Linux
desktop (or WSLg) is required; no debugger or browser service is involved.

```bash
.venv/bin/openwam-live --case 'input/4VPA6B 2.WAM' \
  --executable build-live/bin/release/OpenWAM --runs-dir runs
```

The default panels show engine cycle power, all turbocharger speeds, cylinder 1
pressure, and cylinder 1 temperature. Select variables in the browser (Ctrl/Shift
for multiple selection), then click **Plot selection** in any panel. Overlays must
have matching units and sampling types. Each panel has its own zoom and axes.

- Average results use **Cycle** or **Time** on the horizontal axis.
- Traces use **Cylinder angle** (local to each cylinder) or **Engine angle**
  (common engine reference). Dashed curves show the previous cycle.
- Cursor readouts use the first curve in a panel; latest values are shown for all.
- **Stop** retains partial results and marks the run cancelled.
- **Open saved run…** selects a `results.jsonl` file and replays it without running
  the solver. **Export plotted data…** exports the full recorded history of the
  plotted channels, including older cycles no longer held in plot memory.
- Detailed output is in the collapsed log panel and in `solver.log`. Warnings and
  errors appear above the plots. Closing an active run window requests cancellation.

The first reporting interval can begin partway through a cycle because a WAM case
can start at a nonzero crank angle. These samples are labelled **partial interval**.
Fuel is reported in kg per cylinder per cycle; flow is kg/s, work J, and power kW.
Intake flow is positive into a cylinder; exhaust flow is positive out. Missing or
non-finite values are gaps, not zeros. These are solver results, not a claim that
the model is calibrated or has reached steady state.

## Output isolation and command-line use

Each GUI run creates `runs/<timestamp>-<id>/` containing:

- `results.jsonl`: versioned live results and channel metadata;
- `run.json`: input/executable paths, run status, and wall-clock timing;
- `solver.log`: full merged stdout/stderr;
- the ordinary DAT outputs selected in the WAM input.

The original input is not edited. The solver runs in the input directory so its
relative resource references retain their meaning. Its cleaned temporary WAM and
result files are placed in the run directory.

The C++ executable also supports:

```bash
build-live/bin/release/OpenWAM input/case.WAM \
  --output-dir runs/example --results-stream runs/example/results.jsonl
```

Use a fresh output directory for each case. Existing command-line invocation with
only the WAM argument and existing DAT column selections remain supported. Live
channels do not require editing those selections. In v1, the live channel set is
engine performance, shafts, compressors, turbines, and cylinder pressure,
temperature and valve flows. Pipe/plenum plots, sweeps and model editing are not
part of this application.

## Embedding

`openwam_viewer.viewer.ResultsViewer` is a QWidget with no knowledge of processes,
files or WAM parsing. Its public interface is:

```python
viewer.clear()
viewer.add_channels(descriptors, cycle_degrees=720.0)
viewer.add_sample(sample)
viewer.refresh()
```

Call it on the Qt GUI thread. A 200 ms timer refreshes dirty plots automatically.
`ResultsModel` and `JsonlReader` can also be used without Qt. `RunController` owns
the simulation process; replacing it or the stream adapter does not require
changes to the plots. Keep one QApplication in the embedding host.

### Stream version 1

Every UTF-8 JSON record ends with a newline. Readers retain an incomplete tail
until its newline arrives. Record types are:

- `run`: `schema_version: 1`, `run_id`, `input`, `started_unix`.
- `channels`: `cycle_degrees`, `sample_degrees`, and descriptors containing `id`,
  `component`, `label`, `unit`, `kind` (`average` or `trace`).
- `sample`: `kind`, simulation `time` in seconds, engine `cycle`, and `values`
  keyed by stable channel ID. Trace records also include `angle`, `absolute_angle`,
  `local_angles` keyed by cylinder ID, and `progress` in percent. Average records
  include `interval_start`, `interval_angle_start`, `interval_angle_end`, and
  `partial`. Values may be JSON `null`.
- `end`: `status` (`completed` or `failed`) and `message`. A killed process can
  leave no end record; the run controller records cancellation/failure in `run.json`.

Channels follow `component.number.quantity`, for example `engine.1.power_cycle`,
`shaft.2.rpm`, or `cylinder.3.pressure`. Components are independent objects; a shaft
can have multiple compressors/turbines. Live samples are taken at the first
completed solver step crossing each 1° engine-angle threshold. Their actual angles
are recorded; no intermediate values are fabricated. Buffers are flushed every
200 ms at solver update boundaries and at cycle/completion boundaries. A solver
step or debugger pause longer than 200 ms delays new data until execution resumes.

### Numerical changes

Core engine averages are accumulated and finalized regardless of optional output
flags. Engine friction starts with the speed-dependent terms of the existing loss
model, with the IMEP-dependent term added after the first reporting interval.
Cycle finalization updates that loss state even if engine DAT output is disabled.
Shaft averages accumulate once per step with the previous absolute timestamp.
Engine, shaft, compressor and turbine cycle results finalize before their output
consumers read them. Turbine work/efficiency now cover the reported interval even
when turbine DAT output is disabled, rather than accumulating over the entire run.

## Tests

```bash
OPENWAM_BUILD_DIR=build-live QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m unittest discover -s tests -v
```

The tests cover stream truncation/partial writes, version validation, missing data,
local-angle wraps, bounded trace memory, CSV history, embedding, saved-run replay,
process completion, consecutive runs, warnings, failure and cancellation.
The C++ regression checks unequal timestep weighting and repeated reads of a
finalized shaft average. Omit `OPENWAM_BUILD_DIR` to run only the Python tests.

Run the supplied case through six reporting intervals and compare complete DAT
histories with live output enabled/disabled:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/validate_solver.py \
  --executable build-live/bin/release/OpenWAM \
  --case 'input/4VPA6B 2.WAM' --output /tmp/openwam-validation --viewer
```

Use a new output directory. The script shortens a copy of the case, enables selected
DAT columns for comparison, and leaves the original unchanged. It alternates three
paired runs, checks shaft evolution after 2880°, compares DAT and JSON units/values,
and writes timing measurements to `report.json`. Remove `--viewer` to measure only
the structured output overhead. Headless Qt timings include software rendering;
repeat without `QT_QPA_PLATFORM=offscreen` on the intended desktop for its timings.

### Validation on the supplied case

Debug and Release builds passed, as did all nine automated tests. Six reporting
intervals completed with 38 live channels and shaft speed evolving after 2880°.
Three paired comparisons produced identical average and instantaneous DAT histories
with streaming enabled/disabled. Enabling engine/shaft DAT selections also produced
the same live average values as the original case with those selections disabled.

The stream-only median runtime difference was -0.3% (within timing noise). With
the four plots refreshing at 5 Hz in headless software rendering, the final measured
median overhead was **20.2%** (19.30 s without the viewer versus 23.19 s with it).
The **under-5% total overhead target is not met in this environment**. Desktop
rendering performance still needs measurement on the target machine. Redundant
plot redraws have been removed; neither samples nor refresh frequency were reduced
to obtain these measurements.
