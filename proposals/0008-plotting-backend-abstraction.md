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

This revision (October 2026) brings the document in line with the
implementation after the architecture review on [hyperspy#3623]; see
[Revisions after review](#revisions-after-review).

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

Define a **limited spec** — a core `PlottingBackend` protocol of roughly 85
methods — that captures every drawing primitive the generic layer needs (create
figure / axes, plot line / image / mesh, text, markers, colorbar, events,
blitting, widgets/pointers, scalebar, explorers). Core drawing code calls *only*
these methods; each backend implements them.

Three parts of the contract are deliberately backend-neutral rather than
borrowed from matplotlib:

- **Input events.** Handlers receive HyperSpy's own `KeyEvent`, `PointerEvent`
  and `PickEvent` dataclasses with canonical key names, buttons numbered from 1
  and positions in data and display coordinates. Each backend converts its
  native events before calling a handler.
- **Widgets.** A backend draws widgets as native interactive widgets of its
  library and reports drags in data coordinates. Matplotlib's
  pick-an-artist-then-follow-the-mouse model is an optional `ArtistBackend`
  extension, not part of the core protocol.
- **Behaviour, not just signatures.** A shared conformance test suite defines
  what each method must do, and every backend (built-in or external) runs it.

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
| **Pass native (matplotlib) events and artists through the protocol**  | Every new backend would have to imitate matplotlib's event objects and pick model. Neutral events and native widgets keep the core contract library-agnostic. |
| **Redesign the protocol from scratch before merging** ("v2")          | The review gaps (events, the artist/pick model, testable behaviour) were fixed in place in [hyperspy#3623]; a rewrite would not change the architecture.  |
| **Protocol spec + entry-point registry** (chosen)                     | Minimal core impact, no inheritance coupling, third-party backends are fully external, matplotlib stays default.                                            |

## Impact

- **End users:** No change by default — matplotlib remains the default backend
  and output should be pixel-comparable (no known regressions). anyplotlib is
  strictly opt-in.
- **Backend authors:** Can ship a backend (fastplotlib, pyqtgraph, …) as a
  standalone package via a `hyperspy.backends` entry point, with no hyperspy PR
  required. They start from an annotated template (`_stub.py`), check their
  backend with the shared conformance suite, and follow the developer guide
  section "Plotting backends". The protocol is marked experimental until a
  second, independent backend has been built against it.
- **Downstream widget code:** Event handlers now receive HyperSpy's event
  dataclasses instead of matplotlib's. The commonly used fields (`xdata`,
  `ydata`, `inaxes`, `key`, `button`) keep their names, and the native event
  is still available as `event.native`.
- **Ecosystem / dependencies:** `anyplotlib` is on PyPI; the optional
  `hyperspy[anyplotlib]` extra requires `anyplotlib>=0.11.0`, the first
  release with the public API the backend uses. Testing the browser-rendered
  backend adds an optional `playwright` test dependency (not a runtime
  dependency).
- **Migration path:** None for existing users. Internally, direct matplotlib
  calls in the drawing layer move behind the protocol; the matplotlib backend
  preserves current behavior.
- **Effort:** Large but largely complete in [hyperspy#3623] (~15 new modules;
  the drawing layer refactored behind the protocol). Remaining work:
  - [x] anyplotlib PyPI release (0.11.0, with the public API the backend uses)
  - [x] Playwright test suite
  - [x] Backend-neutral input events and the `ArtistBackend` split
  - [x] Shared backend conformance suite
  - [x] Developer guide section on the backend architecture
  - [x] Follow-up documentation migration.

## Scope

**In scope**

- The `PlottingBackend` protocol and its capability groups.
- The backend-neutral input events and the optional `ArtistBackend` extension.
- The shared behavioural conformance suite.
- Entry-point registry (`hyperspy.backends`) with `available_backends()` /
  `load_backend()`.
- A backend-agnostic generic drawing layer (explorers, markers, norms).
- The **matplotlib reference backend** at feature parity with today.
- The **anyplotlib backend** as a second, browser-native implementation.
- Backend selection API (`Plot.backend` preference, `%anyplotlib` magic).

**Explicitly NOT in scope** (guardrails)

- fastplotlib / pyqtgraph / Bokeh backends — future work, expected to live in
  external packages. Review on [hyperspy#3623] favoured fastplotlib as the next
  candidate for a local GPU backend, and suggested skipping Bokeh. Which one
  to build is a separate decision; the spec only has to make it possible.
- Making the matplotlib-only composers in `drawing/utils.py` (such as
  `plot_images`) backend-agnostic.
- The documentation rewrite to anyplotlib + Pyodide — a separate, dependent PR. Ideally done
  before merging to check that the new backend is actually usable in the docs.
- Any new plotting *features* beyond matching current behavior.

## References

- Reference implementation: [hyperspy#3623] — "Alternative Plotting Backend"
- Developer guide in the implementation: `doc/dev_guide/plotting.rst`,
  section "Plotting backends"
- anyplotlib (browser-native rendering via anywidget): <https://github.com/CSSFrancis/anyplotlib>
- Prior art for the spec-of-ops pattern: tinygrad / PyTorch backend dispatch
- Entry-point plugin precedent in the ecosystem: RosettaSciIO I/O plugins

[hyperspy#3623]: https://github.com/hyperspy/hyperspy/pull/3623

## Technical design

### Package layout

```text
hyperspy/
├── ipython_magic.py             # %anyplotlib IPython magic (importable without drawing/)
└── drawing/
    ├── he.py, hse.py, hie.py    # backend-agnostic explorers (nav/signal/image)
    ├── marker_collection.py     # backend-neutral marker descriptors
    ├── norm.py                  # HyperNorm (backend-neutral colour scaling)
    └── backends/
        ├── _protocol.py         # PlottingBackend, ArtistBackend, tokens, errors
        ├── _events.py           # KeyEvent / PointerEvent / PickEvent + key normalisation
        ├── _registry.py         # entry-point discovery / loading
        ├── _stub.py             # annotated template for a new backend
        ├── mpl/                 # reference backend
        │   ├── __init__.py      #   MplBackend
        │   └── mpl_he.py, mpl_hse.py, mpl_hie.py   # matplotlib explorers
        └── anyplotlib/          # browser-native backend
            ├── __init__.py      #   AnyplotlibBackend
            └── _explorers.py

hyperspy/tests/drawing/
├── backend_conformance.py       # shared suite: BackendConformance + BackendDriver
└── test_backend_conformance.py  # runs it for matplotlib and anyplotlib
```

### The protocol (excerpt)

The protocol is `@runtime_checkable` and split into capability mixins so a
backend can be checked for a subset of features. The core protocol has about
85 methods (`BlitMixin` 10, `PointerMixin` 23, the rest in `PlottingBackend`):

```python
class BlitMixin(Protocol):
    def supports_blit(self, fig) -> bool: ...
    def copy_background(self, fig): ...
    def blit(self, fig) -> None: ...
    # …animation / draw-event methods (no-op defaults)

class PointerMixin(Protocol):
    def create_line_pointer(self, ax, axis, pos, **kw): ...
    def create_rect_pointer(self, ax, pos, w, h, **kw): ...
    def create_circle_pointer(self, ax, ...): ...
    def create_line2d_pointer(self, ax, ...): ...
    def connect_widget_drag(self, handle, on_drag): ...
    def create_span_selector(self, ax, **kw): ...
    # …markers, coordinate conversion

class PlottingBackend(BlitMixin, PointerMixin, Protocol):
    text_markup: str               # a TextMarkup value
    supports_text_rotation: bool

    def create_figure(self, ...): ...
    def create_axes(self, fig, **kw): ...
    def plot_line(self, ax, x, y, **props): ...
    def plot_image(self, ax, data, **kw): ...
    def add_colorbar(self, ...): ...
    def create_scalebar(self, ax, units, **kw): ...
    def connect_key_press(self, fig_or_ax, fn): ...    # fn(KeyEvent)
    def connect_mouse_move(self, fig_or_ax, fn): ...   # fn(PointerEvent)
    def connect_mouse_press(self, fig_or_ax, fn): ...
    def connect_mouse_release(self, fig_or_ax, fn): ...
    def get_explorer(self, signal_dim) -> type[HyperExplorer]: ...
    # …
```

### Backend-neutral tokens

To keep the generic layer free of matplotlib concepts, the protocol trades in
named tokens instead of backend objects:

- `CoordSpace` — `DATA | AXES | DISPLAY | XAXIS | YAXIS | RELATIVE` for
  coordinate conversion (`convert_coords`).
- `MarkerType` — `POINTS | CIRCLES | SQUARES | LINES | HLINES | VLINES | TEXTS |
  RECTANGLES | ELLIPSES | ARROWS | POLYGONS`.
- `TextMarkup` — `MATHTEXT | TEX_LITE | HTML | PLAIN`, the richest text markup a
  backend renders. Marker texts that need more than the backend declares are
  degraded (for example, mathtext to plain unicode) instead of failing.

### Input events

Every backend converts its native events into frozen dataclasses from
`_events.py` before calling a handler; the generic layer never sees a
library's event object.

```python
@dataclass(frozen=True)
class PointerEvent:
    kind: str                  # "move" | "press" | "release"
    xdata: float | None        # data coordinates of inaxes; None outside
    ydata: float | None
    inaxes: Any                # backend axes handle, or None
    x: float | None            # display coordinates
    y: float | None
    button: int | None         # 1 left, 2 middle, 3 right
    modifiers: frozenset       # from {"ctrl", "alt", "shift", "super"}
    dblclick: bool
    native: Any                # the backend's own event
```

`KeyEvent` carries a canonical key name: lower-case named keys (`"left"`,
`"pageup"`) prefixed by held modifiers in a fixed order (`"ctrl+left"`).
`canonical_key()` maps the common spellings (the browser's `"ArrowLeft"`,
Qt's `"meta"`), so keyboard navigation works the same on every backend.
`PickEvent` exists only for the artist extension below.

### Widgets: native widgets vs. the artist extension

Widgets (navigation pointers, ROI widgets) own their geometry and events; the
backend only draws them and reports user input. A backend does this in one of
two ways:

| | Native widgets (core protocol) | Pickable artists (`ArtistBackend`) |
|---|---|---|
| Used by | anyplotlib | matplotlib |
| Drawing | `create_*_pointer` creates the library's interactive widget | `create_*_pointer` creates a plain artist |
| Dragging | The library moves the widget and calls `connect_widget_drag` with the new geometry in data coordinates | A `PickEvent` selects the widget, then `PointerEvent`s move it until release |

`ArtistBackend` holds the 9 matplotlib-shaped methods (`add_artist`,
`connect_pick`, `simulate_pick`, `get_ax_transform`, raw `Collection`
support, `tight_layout`, …). The generic layer only calls them through
`get_artist_backend()`, which returns `None` unless the backend implements
the whole extension. A new backend is expected to use native widgets and not
implement it. Without it, widgets have no separate resize handles, markers
built from a raw matplotlib `Collection` raise `BackendCapabilityError`, and
`tight_layout` is skipped.

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
fastplotlib = "hyperspy_fastplotlib.backend:FastplotlibBackend"
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
on day one, and partial backends remain usable. A user request that cannot be
honoured at all (such as a raw-`Collection` marker on a native-widget backend)
raises it to the user.

### Conformance suite

`hyperspy/tests/drawing/backend_conformance.py` defines what the protocol
methods must *do*, not only their signatures. A backend subclasses
`BackendConformance` and provides a `BackendDriver` that emits the library's
own native events, exactly as a user interacting with it would:

```python
class TestMyBackendConformance(BackendConformance):
    backend_name = "mybackend"          # the entry-point name

    @pytest.fixture
    def backend(self):
        return MyBackend()

    @pytest.fixture
    def driver(self):
        return MyDriver()               # fire_key / fire_pointer / drag_pointer
```

The suite covers the protocol shape (including the all-or-nothing artist
extension), drawing primitives and their update/remove lifecycle, coordinate
conversion, every widget primitive including a real drag or pick, the
input-event contract (canonical keys and buttons, data coordinates,
disconnection) and end-to-end `Signal1D` / `Signal2D` navigation, keyboard
navigation and ROI widgets. Features a backend declares unsupported with
`BackendCapabilityError` are skipped, not failed. Third-party backends run
the same suite from their own test suite.

### Verification (in the implementation PR)

- Matplotlib backend: existing `drawing` tests plus image-comparison baselines
  guard against regressions.
- Protocol / registry: `test_backend_protocol.py`, `test_backend_registry.py`,
  `test_backend_integration.py`, `test_generic_layer_purity.py` assert the core
  layer stays matplotlib-free and that discovery/loading works.
- Both built-in backends pass the shared conformance suite.
- anyplotlib backend: a `playwright`-driven suite renders real figures in a
  browser and compares PNG output against baselines.

## Revisions after review

The architecture review on [hyperspy#3623] (October 2026) argued that the
first version of the protocol was too matplotlib-shaped. These changes were
made in the implementation and are reflected above:

| Review point | Change |
|---|---|
| Handlers received matplotlib event objects, so other backends had to imitate them | Backend-neutral `KeyEvent` / `PointerEvent` / `PickEvent` with canonical keys and buttons (this also fixed arrow-key navigation on anyplotlib) |
| Pick/artist methods and `tight_layout` in the core protocol only make sense for matplotlib | Moved to the optional `ArtistBackend` extension; native widgets with `connect_widget_drag` are the core path |
| A protocol of signatures does not say what a backend must do | Shared behavioural conformance suite, run by both built-in backends and available to external ones |
| The anyplotlib backend relied on anyplotlib internals | anyplotlib 0.11.0 added a public API (data-coordinate widgets, close events, image extents) and the backend uses only that |
| Backend authors had no documentation | Developer guide section "Plotting backends" and an annotated `_stub.py` template |
| Which backend comes next (pyqtgraph, Bokeh, fastplotlib) | Left out of scope; fastplotlib was favoured in the discussion |
