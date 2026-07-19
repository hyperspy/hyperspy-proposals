---
proposal: 8
title: "A pluggable plotting-backend abstraction for HyperSpy"
type: Architecture
target_branch: hyperspy/hyperspy:RELEASE_next_minor
target_repos: [hyperspy/hyperspy]
status: review
ai_assisted: true
created: 2026-07-19
---

## Summary

HyperSpy's interactive plotting is wired directly to matplotlib throughout the
`drawing` layer, which makes it impossible to add a different renderer. Matplotlib
is a vector based graphing utility which is important for scalable, and high quality
figures, but it is slow and difficult to update. For large datasets, or images it is
insufficient. This proposal introduces a small, explicit `PlottingBackend` **protocol** —
a fixed spec of drawing operations. This is inspired by the way that Tinygrad defined
a narrow operation spec that each compute backend satisfies. In addition there is a
**registry**, so that `signal.plot()` is backend-agnostic and new backends can be registered
from external packages without touching hyperspy. Matplotlib stays the default and reference
backend; a second `anyplotlib` backend is included to prove the abstraction is
real. **The decision requested:** accept this protocol-based approach (reference
implementation in [hyperspy#3623]) as the way forward, targeting
`RELEASE_next_minor`.

## Problem

Today, plotting logic and matplotlib are entangled at every level of
`hyperspy/drawing/`:

- Figure and axes creation, event connection, blitting, widgets, markers,
  colorbars, and scalebars all call matplotlib APIs directly.
- Signal explorers (`signal1d.py`, `image.py`, the `mpl_h*e` classes) mix
  *what* to draw (a navigator, a spectrum, a pointer) with *how* matplotlib
  draws it.

Consequences:

- **No path to other renderers.** Web-native (anywidget/Pyodide), GPU
  (fastplotlib), or Qt (pyqtgraph) backends would each require invasive,
  parallel rewrites of the drawing layer.
- **Frontend limitations are baked in.** The current interactive path depends
  on matplotlib's `ipympl`, which streams server-rendered images over a Jupyter
  comm and needs a live kernel for every mouse interaction. That rules out
  kernel-less frontends such as Marimo and JupyterLite and makes remote
  interactivity laggy.

## Proposed approach

Define a **limited spec** — a `PlottingBackend` protocol of roughly 60 methods —
that captures every drawing primitive the generic layer needs (create figure /
axes, plot line / image/ mesh, text, markers, colorbar, events, blitting,
widgets/pointers, scalebar, explorers). Core drawing code calls *only* these
methods; each backend implements them.

The design is deliberately modelled on how projects like **tinygrad / PyTorch**
define a narrow operation spec that every compute backend satisfies. The payoff
is the same: minimal, localized impact on the existing codebase, and a clear
contract that makes new backends additive rather than invasive.

Backends are discovered through Python **entry points** (group
`"hyperspy.backends"`), exactly like RosettaSciIO plugins — so an external
package registers a backend in its own `pyproject.toml` with zero changes to
hyperspy. Matplotlib and anyplotlib are registered by hyperspy itself through
the same mechanism, so built-in and third-party backends are on equal footing.

(Alternatively the anyplotlib backend could be vendored into hyperspy, although it
is fairly small so I'd recommend vendoring it with hyperspy. It also has GPU
acceleration for images over 1k x 1k pixels and support for 3D Rendering.)

Selection is opt-in and non-breaking: matplotlib is the default; a user
switches with the `Plot.backend` preference or the `%anyplotlib` IPython magic.

### Alternatives considered

| Alternative                                                           | Why not                                                                                                                                                     |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Status quo** (matplotlib-only)                                      | No path to web-native / GPU ; frontend limits (Marimo, JupyterLite) stay baked in.                                                                          |
| **Ad-hoc duck-typing / monkeypatching** a second renderer in          | No explicit contract; brittle; every core change risks silently breaking the alternate path.                                                                |
| **Adopt one new renderer as the single backend** (e.g. plotly/bqplot) | Swaps one hard dependency for another without making the layer pluggable; strands matplotlib users.                                                         |
| **Abstract base classes (ABC)** instead of a Protocol                 | Forces external backends to import from and inherit hyperspy internals; structural `Protocol` typing lets a backend satisfy the spec without that coupling. |
| **Protocol spec + entry-point registry** (chosen)                     | Minimal core impact, no inheritance coupling, third-party backends are fully external, matplotlib stays default.                                            |

## Impact

- **End users:** No change by default — matplotlib remains the default backend
  and output should be pixel-comparable (no known regressions). anyplotlib is
  strictly opt-in.
- **Backend authors:** Can ship a backend (pyqtgraph, fastplotlib, …) as a
  standalone package via a `hyperspy.backends` entry point, with no hyperspy PR
  required.
- **Ecosystem / dependencies:** `anyplotlib` must be published to PyPI (today
  it lives at `CSSFrancis/anyplotlib`) before its backend is generally usable.
  Testing the browser-rendered backend adds an optional `playwright` test
  dependency (not a runtime dependency).
- **Migration path:** None for existing users. Internally, direct matplotlib
  calls in the drawing layer move behind the protocol; the matplotlib backend
  preserves current behavior.
- **Effort:** Large but largely complete in [hyperspy#3623] (~15 new modules;
  the drawing layer refactored behind the protocol). Remaining work:
  - [x] anyplotlib PyPI release
  - [x] Playwright test suite
  - [x] Follow-up documentation migration.

## Scope

**In scope**

- The `PlottingBackend` protocol and its capability groups.
- Entry-point registry (`hyperspy.backends`) with `available_backends()` /
  `load_backend()`.
- A backend-agnostic generic drawing layer (explorers, markers, norms).
- The **matplotlib reference backend** at feature parity with today.
- The **anyplotlib backend** as a second, browser-native implementation.
- Backend selection API (`Plot.backend` preference, `%anyplotlib` magic).

**Explicitly NOT in scope** (guardrails)

- pyqtgraph / fastplotlib backends — future work, expected to live in external
  packages. (maybe not ever done, but the spec is designed to make it possible)
- The documentation rewrite to anyplotlib + Pyodide — a separate, dependent PR. Ideally done
  before merging to check that the new backend is actually usable in the docs.
- Any new plotting *features* beyond matching current behavior.

## References

- Reference implementation: [hyperspy#3623] — "Alternative Plotting Backend"
- anyplotlib (browser-native rendering via anywidget): <https://github.com/CSSFrancis/anyplotlib>
- Prior art for the spec-of-ops pattern: tinygrad / PyTorch backend dispatch
- Entry-point plugin precedent in the ecosystem: RosettaSciIO I/O plugins

[hyperspy#3623]: https://github.com/hyperspy/hyperspy/pull/3623

## Technical design

### Package layout

```text
hyperspy/drawing/
├── he.py, hse.py, hie.py        # backend-agnostic explorers (nav/signal/image)
├── marker_collection.py         # backend-neutral marker descriptors
├── norm.py                      # HyperNorm (backend-neutral colour scaling)
└── backends/
    ├── _protocol.py             # PlottingBackend protocol + tokens + errors
    ├── _registry.py             # entry-point discovery / loading
    ├── _magic.py                # %anyplotlib IPython magic
    ├── _stub.py                 # minimal stub backend (tests / fallback)
    ├── mpl/                     # reference backend
    │   ├── __init__.py          #   MplBackend
    │   └── mpl_he.py, mpl_hse.py, mpl_hie.py   # matplotlib explorers
    └── anyplotlib/              # browser-native backend
        ├── __init__.py          #   AnyplotlibBackend
        └── _explorers.py
```

### The protocol (excerpt)

The protocol is `@runtime_checkable` and split into capability mixins so a
backend can be checked for a subset of features:

```python
class BlitMixin(Protocol):
    def supports_blit(self, fig) -> bool: ...
    def copy_background(self, fig): ...
    def blit(self, fig) -> None: ...
    # …animation / draw-event methods

class PointerMixin(Protocol):
    def create_line_pointer(self, ax, axis, pos, **kw): ...
    def create_rect_pointer(self, ax, pos, w, h, **kw): ...
    def create_span_selector(self, ax, **kw): ...
    # …widgets, markers, coordinate transforms

class PlottingBackend(BlitMixin, PointerMixin, Protocol):
    def create_figure(self, ...): ...
    def create_axes(self, fig, **kw): ...
    def plot_line(self, ax, x, y, **props): ...
    def plot_image(self, ax, data, **kw): ...
    def add_colorbar(self, ...): ...
    def create_scalebar(self, ax, units, **kw): ...
    def get_explorer(self, signal_dim) -> type[HyperExplorer]: ...
    # …~60 methods total
```

### Backend-neutral tokens

To keep the generic layer free of matplotlib concepts, the protocol trades in
named tokens instead of backend objects:

- `CoordSpace` — `DATA | AXES | DISPLAY | XAXIS | YAXIS | RELATIVE` for
  coordinate conversion (`convert_coords`, `get_ax_transform`).
- `MarkerType` — `POINTS | CIRCLES | SQUARES | LINES | HLINES | VLINES | TEXTS |
  RECTANGLES | ELLIPSES | ARROWS | POLYGONS`.

### Registration (entry points)

Built-in, in hyperspy's `pyproject.toml`:

```toml
[project.entry-points."hyperspy.backends"]
matplotlib = "hyperspy.drawing.backends.mpl:MplBackend"
anyplotlib = "hyperspy.drawing.backends.anyplotlib:AnyplotlibBackend"
```

An external backend registers identically from its own package:

```toml
[project.entry-points."hyperspy.backends"]
pyqtgraph = "hyperspy_pyqtgraph.backend:PyQtGraphBackend"
```

### Selection

```python
import hyperspy.api as hs
from hyperspy.defaults_parser import preferences

preferences.Plot.backend = "anyplotlib"   # or the %anyplotlib IPython magic
s.plot()                                    # renders through the chosen backend
```

### Graceful degradation

A backend that cannot honor a request raises `BackendCapabilityError`
(subclass of `NotImplementedError`). The generic layer catches it to skip or
warn rather than crash — so a backend need not implement every optional feature
on day one, and partial backends remain usable.

### Verification (in the implementation PR)

- Matplotlib backend: existing `drawing` tests plus image-comparison baselines
  guard against regressions.
- Protocol / registry: `test_backend_protocol.py`, `test_backend_registry.py`,
  `test_backend_integration.py`, `test_generic_layer_purity.py` assert the core
  layer stays matplotlib-free and that discovery/loading works.
- anyplotlib backend: a `playwright`-driven suite renders real figures in a
  browser and compares PNG output against baselines.
