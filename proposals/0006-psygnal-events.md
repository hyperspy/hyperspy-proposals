---
proposal: 0006
title: "Migrate the events system to psygnal — eliminate exec bottlenecks and enable live processing"
type: Architecture
target_branch: [hyperspy/hyperspy:RELEASE_next_minor, hyperspy/hyperspy:RELEASE_next_major]
target_repos: [hyperspy/hyperspy]
status: review
ai_assisted: true
created: 2026-07-04
---

# Migrate the Events System to psygnal

## Summary

Replace HyperSpy's 10-year-old custom event system (`hyperspy/events.py`) with a psygnal-backed implementation that eliminates the fragile `exec()`-based trigger generation, adds weakref-based listener leak prevention, and introduces a psygnal-native dual API (`emit()`, `blocked()`, `__call__()`). In HyperSpy 2.5, the old API (`trigger()`, `suppress()`, `suppress_callback()`, `connect(kwargs=...)`) remains as deprecated aliases emitting `VisibleDeprecationWarning` — all internal HyperSpy code is migrated to the new API, and downstream packages (pyxem, exspy, lumispy) get a full release cycle to migrate. In HyperSpy 3.0, the old API surface is removed.

## Problem

HyperSpy's event system was designed ~10 years ago and has three concrete bottlenecks:

1. **`_trigger_maker` uses `exec()` + `sys._getframe()`** to dynamically generate trigger functions with type-checked signatures. This is fragile, version-specific (the code branches on `sys.version_info.minor >= 13`), and a security concern. It generates a `trigger()` method via `exec()` with `@wraps(f)` decorators and `locals()` manipulation every time an `Event` is constructed with `arguments=`.

2. **Three separate callback collections** (`_connected_all`, `_connected_some`, `_connected_map`) are iterated sequentially on every trigger. There is no batching, no throttling, no debouncing — every `data_changed.trigger()` fires all connected callbacks synchronously, even during rapid mutations (~78 trigger sites across the codebase).

3. **No weakref tracking** — every `connect()` requires a manual `disconnect()`, and listener leaks are HyperSpy's most common bug class (PR [#3355](https://github.com/hyperspy/hyperspy/pull/3355), [#3640](https://github.com/hyperspy/hyperspy/pull/3640), [#3629](https://github.com/hyperspy/hyperspy/pull/3629), [#3648](https://github.com/hyperspy/hyperspy/pull/3648)). There is no auto-disconnect when the owning object is garbage collected.

Additionally, the system has **no async dispatch** — zero `async`/`await` anywhere in the codebase, and the event system blocks the calling thread for all callbacks. This is incompatible with the planned live/streaming processing feature.

### Concrete examples

A widget connects to `axes_manager.events.indices_changed`:

```python
# drawing/widget.py
self.axes_manager.events.indices_changed.connect(self._on_navigate, ["obj"])
```

If the widget is destroyed without calling `disconnect()`, the bound method `self._on_navigate` stays alive — held by the event's callback collection — and fires on every navigation change, operating on a dead widget. This is the exact pattern behind PRs #3355, #3640, #3629, #3648.

The `exec()`-based trigger generation:

```python
# events.py (old)
wrap_code = """
@wraps(f)
def trigger(self, %s):
    return f(%s)
""" % (arglist, arg_pass)
if sys.version_info.minor >= 13:
    locals_ = sys._getframe().f_locals
else:
    locals_ = locals()
exec(wrap_code, gl, locals_)
```

This generates a new function via `exec()` every time an `Event` is constructed with `arguments=` (14 production sites). It is the single most fragile piece of code in the events module.

## Proposed approach

Rewrite `hyperspy/events.py` as a psygnal-backed implementation. The `Event`, `Events`, and `EventSuppressor` classes remain as the public API in 2.5, but a psygnal-native dual API is added (`emit()`, `blocked()`, `__call__()`), all internal HyperSpy code is migrated to it, and the old API emits `VisibleDeprecationWarning`.

The migration is a single coherent change with three concerns, each independently revertible:

1. **psygnal adapter with weakref default** — rewrite `events.py` to use psygnal under the hood for connection management and dispatch. `weakref=True` becomes the default for `connect()` with a kill-switch (`HS_EVENT_WEAKREF=0` env var) for downstream compatibility. Fixes the #1 bug class (listener leaks).
2. **Eliminate `exec()`** — remove `_trigger_maker`, reimplement `arguments=` validation with `inspect.Signature`-based runtime validation. Add throttling/debouncing support (psygnal built-in).
3. **psygnal-native dual API + deprecation** — add `emit()`, `blocked()`, `__call__()` as the preferred API. Migrate all ~78 internal `trigger()` calls to `emit()`, all ~30 `connect(fn, [])` to `connect(fn)` (with lambda wrappers where needed), all 4 `connect(fn, {dict})` to explicit lambda wrappers, all 9 `suppress()` to `blocked()`, and the 1 `suppress_callback()` to the guard-flag pattern. The old API stays as deprecated aliases with `VisibleDeprecationWarning`.

In **HyperSpy 3.0** (separate future PR), the old `Event`/`Events`/`EventSuppressor` API is removed and psygnal's native `Signal`/`SignalGroup` becomes the public API.

### Why psygnal

psygnal is built by the [napari](https://github.com/napari/napari) maintainers (pyapp-kit team) specifically for scientific Python imaging — the same domain as HyperSpy. It provides:

- **mypyc-compiled dispatch** — faster than pure-Python callback iteration.
- **`EventedObjectProxy`** — detects numpy array mutations without manual `trigger()` calls (future: eliminate manual `data_changed.trigger()` sites).
- **`EventedModel`** — pydantic v2 model that auto-emits signals on field changes (future: parameter models).
- **`Evented containers`** — `EventedList`, `EventedDict`, `EventedSet` for axes manager.
- **anywidget compatibility** — future-proofs Jupyter widget integration.
- **Throttling/debouncing** — built-in, for high-frequency events during live processing.
- **Zero required dependencies** — BSD-3 licensed, available on conda-forge.
- **Active maintenance** — used in production by napari (a major scientific imaging tool).

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| **blinker** (Flask signals) | Battle-tested but too generic — no numpy mutation detection, no evented containers, no anywidget compatibility, no scientific ecosystem adoption. Would require building attribute watching on top. |
| **traitlets** (Jupyter) | Jupyter-native but requires `HasTraits` inheritance (heavy coupling), no async support, no streaming. Confusing alongside HyperSpy's existing Enthought `traits` usage (separate system). |
| **pyee** | Excellent async support (asyncio, trio, twisted) but single-maintainer risk, no scientific ecosystem integration, no attribute observation. |
| **RxPy** (ReactiveX) | Full reactive programming framework — wrong paradigm. Steep learning curve, no scientific ecosystem adoption. HyperSpy needs property-change notifications, not observable streams. |
| **zope.event** | Too minimal — no typing, no async, no sender filtering. Provides nothing HyperSpy can't already do. |
| **Keep custom events.py** | Would require reimplementing weakref tracking, throttling, async dispatch, and numpy mutation detection from scratch. psygnal already provides all of these, battle-tested in napari. |

## Impact

### Non-breaking (2.5)

- All downstream consumer code (pyxem, exspy, lumispy, user scripts) remains unchanged — the old API is preserved as deprecated aliases with `VisibleDeprecationWarning`.
- All existing tests pass: `test_events.py`, `test_interactive.py`, `test_figure.py`, `test_widget.py`, `test_parameter.py`, `test_samfire.py`, and the full test suite.
- Every current behavior is preserved: `ValueError` on duplicate connect, `ValueError` on disconnect-not-connected, `.connected` set property, exception-abort semantics (one failing callback aborts remaining dispatch), `EventSuppressor`, `Events` dynamic registration, dict-rename `connect(fn, {"obj": "widget"})`, `arguments=` validation, `kwargs="auto"` mode, `__deepcopy__`.
- HyperSpy's Enthought `traits` system (used for GUI configuration) is completely separate and unaffected.

### Breaking (2.5 — weakref default)

One intentional behavior change: `weakref=True` becomes the default for `Event.connect()`. Bound methods of garbage-collected objects now auto-disconnect. This is the explicit accepted risk — it fixes the #1 bug class (listener leaks) but could break code that relies on the event keeping bound methods alive. Mitigations:

- **Kill-switch**: `HS_EVENT_WEAKREF=0` environment variable disables weakref globally.
- **Per-connection opt-out**: `connect(f, weakref=False)` restores old behavior for specific connections (emits `VisibleDeprecationWarning`).
- **Lambdas unaffected**: psygnal holds strong references for non-weakrefable callables (lambdas, module-level functions).

### Breaking (3.0 — future PR)

In HyperSpy 3.0, the old API surface is removed:

- `Event`/`Events`/`EventSuppressor` → psygnal `Signal`/`SignalGroup`.
- `trigger()` → `emit()`.
- `suppress()` → `blocked()`.
- `connect(kwargs=...)` → `connect()` with explicit wrapper functions.
- `arguments=` parameter → psygnal type-annotated Signals.
- `weakref` parameter removed (always on).
- `_trigger_maker` removed.

Downstream packages get a full 2.5 release cycle with deprecation warnings to migrate.

### Effort

| Concern | Effort | Description |
|---|---|---|
| psygnal adapter + weakref | Large | Rewrite events.py to use psygnal, preserve all behaviors, weakref=True default with kill-switch, regression tests |
| Eliminate exec | Medium | Replace `_trigger_maker` with `inspect.Signature` validation, throttling/debouncing, perf benchmarks |
| Dual API + deprecation | Large | Add emit()/blocked()/**call**(), migrate ~78 trigger + ~30 connect([]) + 4 connect({}) + 9 suppress + 1 suppress_callback, enable VisibleDeprecationWarning, 15 new tests, changelog, 3.0 roadmap doc |
| Total | XL | 36 files changed, 66 event tests, all verification passed |

### Affected repos

| Repo | Changes |
|---|---|
| `hyperspy/hyperspy` | `events.py` rewrite, `pyproject.toml` (new dependency + warning filters), `conda_environment*.yml`, 26 production files (call-site migration), `tests/test_events.py` (+15 tests), `tests/test_events_performance.py` (new), `tests/__init__.py` (warning filters), `upcoming_changes/`, `doc/user_guide/events_migration.rst` (3.0 roadmap) |

## Scope

### What's included

- `hyperspy/events.py` rewritten as psygnal-backed implementation — `Event`, `Events`, `EventSuppressor` public API preserved.
- `psygnal>=0.10` added as hard dependency in `pyproject.toml`, `conda_environment.yml`, `conda_environment_dev.yml`.
- `_trigger_maker` `exec()` + `sys._getframe()` eliminated — replaced with `inspect.Signature`-based runtime validation.
- Three-collection sequential dispatch replaced with psygnal-style connection management + per-connection kwarg adapter wrappers.
- `weakref=True` default for `Event.connect()` with kill-switch (`HS_EVENT_WEAKREF=0` env var) and per-connection opt-out (`weakref=False`).
- Throttling/debouncing support (`Event.throttle(interval)`, `Event.debounce(interval)` context managers) for high-frequency events.
- `max_listeners` parameter on `connect()` for leak detection in development.
- Psygnal-native dual API: `Event.emit(*args)`, `Event.__call__(*args)`, `Event.blocked()`, `Events.blocked()`.
- `VisibleDeprecationWarning` on all deprecated methods: `trigger()`, `suppress()`, `Events.suppress()`, `suppress_callback()`, `connect(kwargs=...)` (non-`"all"`), `connect(weakref=False)`, `arguments=`.
- All ~78 internal `trigger()` calls migrated to `emit()` across 15 production files.
- All ~30 `connect(fn, [])` calls migrated to `connect(fn)` (with lambda wrappers where the callback does not accept `**kwargs`/`*args`).
- All 4 `connect(fn, {dict})` dict-rename calls migrated to explicit `connect(lambda obj: fn(widget=obj))` wrappers.
- All 9 `suppress()` calls migrated to `blocked()`.
- The 1 `suppress_callback()` call migrated to the guard-flag pattern (callback owns its boolean suppression flag, checks it at entry, returns early when suppressed).
- 3.0 migration roadmap document in `doc/user_guide/events_migration.rst` with guard-flag pattern example.
- 15 new regression tests (66 total in `test_events.py`) covering emit/blocked/call-alias/deprecation-warnings.
- Performance benchmarks in `test_events_performance.py`.
- Changelog entries in `upcoming_changes/`.

### What's explicitly NOT included

- Changes to any downstream consumer files — the old API is preserved as deprecated aliases.
- Changes to `hyperspy/api.py` `__all__` exports.
- Changes to Enthought `traits` usage (separate system, unaffected).
- Introduction of `async`/`await` in any consumer code — 2.5 is synchronous-only.
- The 3.0 breaking changes — only deprecation warnings and migration documentation in 2.5.
- `EventedObjectProxy` for numpy array mutation detection (3.0 feature).
- `EventedModel` for pydantic v2 parameter models (3.0 feature).
- Live/streaming processing implementation (future, post-3.0).

## References

- [psygnal documentation](https://psygnal.readthedocs.io/) — Signal, SignalGroup, EventedObjectProxy, EventedModel
- [psygnal GitHub](https://github.com/pyapp-kit/psygnal) — BSD-3, zero required dependencies, mypyc-compiled
- [napari](https://github.com/napari/napari) — primary scientific Python user of psygnal
- PR [#3355](https://github.com/hyperspy/hyperspy/pull/3355) — listener leak fix
- PR [#3640](https://github.com/hyperspy/hyperspy/pull/3640) — listener leak fix
- PR [#3629](https://github.com/hyperspy/hyperspy/pull/3629) — listener leak fix
- PR [#3648](https://github.com/hyperspy/hyperspy/pull/3648) — listener leak fix
- issue [#3630](https://github.com/hyperspy/hyperspy/issues/3630) — discussion on events migration
- Proposal [0005](https://github.com/hyperspy/hyperspy-proposals/pull/5) — Lazy Expressions (depends on events for staleness detection)

## Technical design

### Current architecture

```text
hyperspy/events.py (old, 569 lines)
├── Events (container)
│   ├── __setattr__/__getattr__/__delattr__ magic (dynamic Event registration)
│   ├── suppress() — sets _suppress=True on all contained Events
│   └── _update_doc() — auto-generates docstrings
├── Event (individual signal/slot)
│   ├── _trigger_maker() — exec()-based dynamic trigger signature generation
│   ├── connect(f, kwargs="all"|"auto"|list|dict) — 3 collections
│   ├── disconnect(f) — removes from whichever collection
│   ├── trigger(**kwargs) — iterates 3 collections sequentially
│   ├── suppress() — sets _suppress=True
│   ├── suppress_callback(f) — per-callback suppression
│   ├── connected property — returns set of all registered functions
│   └── __deepcopy__ — new Event with no connections
└── EventSuppressor (composite suppression)
    ├── add(Event|Events|(Event,callback)|(Events,callback)|iterable)
    └── suppress() — enters all context managers simultaneously
```

### New architecture (2.5)

```text
hyperspy/events.py (new, 1037 lines)
├── Events (container — public API preserved)
│   ├── __setattr__/__getattr__/__delattr__ magic (preserved — psygnal SignalGroup is declarative, incompatible)
│   ├── blocked() — NEW: iterates contained Events, calls each blocked()
│   ├── suppress() — DEPRECATED: delegates to blocked() with VisibleDeprecationWarning
│   └── _update_doc() — preserved
├── Event (psygnal-backed)
│   ├── __init__(doc, arguments, max_listeners) — arguments= validated via inspect.Signature (no exec)
│   ├── emit(*args, **kwargs) — NEW: maps positional args via _arguments, dispatches
│   ├── __call__(*args, **kwargs) — NEW: alias for emit()
│   ├── trigger(*args, **kwargs) — DEPRECATED: delegates to emit() with VisibleDeprecationWarning
│   ├── blocked() — NEW: context manager (counter-based, nestable)
│   ├── suppress() — DEPRECATED: delegates to blocked() with VisibleDeprecationWarning
│   ├── suppress_callback(f) — DEPRECATED: warns; stays functional for backward compat
│   ├── connect(f, kwargs, weakref, max_listeners) — creates wrapper, optional weakref
│   │   ├── kwargs="all" → wrapper passes all emit kwargs
│   │   ├── kwargs="auto" → wrapper inspects f's signature
│   │   ├── kwargs=["a","b"] → wrapper filters kwargs
│   │   ├── kwargs={"a":"b"} → wrapper remaps kwargs (dict-rename)
│   │   ├── weakref=True → WeakMethod for bound methods, strong ref for lambdas
│   │   └── weakref=False → strong ref (deprecated, warns)
│   ├── disconnect(f) — removes f's wrapper, raises ValueError if not connected
│   ├── throttle(interval) — NEW: context manager, limits dispatch to once per interval
│   ├── debounce(interval) — NEW: context manager, defers dispatch until silence
│   ├── connected property → returns set of original functions (not wrappers)
│   └── __deepcopy__ — new Event with no connections
└── EventSuppressor (composite — public API preserved)
    ├── add(Event|Events|(Event,callback)|(Events,callback)|iterable)
    └── suppress() — enters all Event.suppress()/suppress_callback() context managers
```

### Per-connection kwarg adapter

The core complexity is bridging HyperSpy's `trigger(**kwargs)` to psygnal's positional `emit()`. Each connected function gets a wrapper:

```python
# kwargs="all" — pass all emit kwargs through
def wrapper(**event_kwargs):
    function(**event_kwargs)

# kwargs=["obj"] — filter to only requested kwargs
def wrapper(**event_kwargs):
    function(**{kw: event_kwargs.get(kw, None) for kw in kw_list})

# kwargs={"obj": "widget"} — dict-rename: trigger kwarg "obj" → function param "widget"
def wrapper(**event_kwargs):
    function(**{fn: event_kwargs[tn] for tn, fn in rename_map.items()})
```

### weakref with kill-switch

```python
import os

class Event:
    def connect(self, function, kwargs="all", weakref=None, max_listeners=None):
        if weakref is None:
            weakref = os.environ.get("HS_EVENT_WEAKREF", "1") != "0"
        if weakref is False:
            warnings.warn(
                "weakref=False is deprecated and will be removed in 3.0. "
                "Use HS_EVENT_WEAKREF=0 env var for global opt-out.",
                VisibleDeprecationWarning, stacklevel=2,
            )
        # Weakref only applies to kwargs="all" with bound methods.
        # Plain functions/lambdas cannot be weak-referenced.
        use_weakref = weakref and resolved_kwargs == "all" and inspect.ismethod(function)
        if use_weakref:
            ref = weakref.WeakMethod(function)
            def wrapper(**event_kwargs):
                fn = ref()
                if fn is not None:
                    fn(**event_kwargs)
```

### arguments= validation without exec

```python
class Event:
    def __init__(self, doc="", arguments=None, max_listeners=None):
        if arguments is not None:
            warnings.warn(
                "The 'arguments' parameter is deprecated and will be removed "
                "in HyperSpy 3.0. Use psygnal.Signal with type annotations.",
                VisibleDeprecationWarning, stacklevel=2,
            )
        self._arguments = tuple(arguments) if arguments else None
        self._signal = psygnal.Signal()  # dormant, for 3.0 cutover
        if arguments:
            self._arg_names = []
            self._arg_defaults = {}
            for arg in arguments:
                if isinstance(arg, (tuple, list)):
                    name, default = arg[0], arg[1]
                    self._arg_names.append(name)
                    self._arg_defaults[name] = default
                else:
                    self._arg_names.append(arg)

    def emit(self, *args, **kwargs):
        # Map positional args to named arguments
        if self._arguments is not None and args:
            for i, value in enumerate(args):
                if i < len(self._arg_names):
                    kwargs[self._arg_names[i]] = value
        # Validate against arguments= signature
        if self._arguments is not None:
            for key in kwargs:
                if key not in self._arg_names:
                    raise TypeError(
                        f"emit() got an unexpected keyword argument '{key}'"
                    )
        self._dispatch(**kwargs)
```

### Guard-flag pattern (replaces suppress_callback)

The single production `suppress_callback()` call (in `model.py`) is migrated to the guard-flag pattern — the psygnal-native replacement where the callback checks its own boolean flag and returns early:

```python
# In BaseModel.__init__:
self._suppress_fetch_stored_values = False

# The callback checks the flag:
def _on_indices_changed(self, obj):
    if self._suppress_fetch_stored_values:
        return
    self.fetch_stored_values(obj)

# Context manager for suppression (save/restore for re-entrancy):
@contextmanager
def _suppress_fetch(self):
    old = self._suppress_fetch_stored_values
    self._suppress_fetch_stored_values = True
    try:
        yield
    finally:
        self._suppress_fetch_stored_values = old

# Usage (replaces suppress_callback):
with self._suppress_fetch():
    self._update_something()
```

### 3.0 migration mapping

| 2.5 API | 3.0 API |
|---|---|
| `obj.events.data_changed.trigger(obj=self)` | `obj.data_changed.emit(self)` |
| `obj.events.data_changed.connect(f, kwargs=["obj"])` | `obj.data_changed.connect(lambda obj: f(obj=obj))` |
| `obj.events.data_changed.connect(f, kwargs={"obj": "widget"})` | `obj.data_changed.connect(lambda obj: f(widget=obj))` |
| `with obj.events.suppress():` | `with obj.data_changed.blocked():` |
| `with obj.events.data_changed.suppress_callback(f):` | Guard-flag pattern (callback checks own flag) |
| `Event(arguments=["obj", "value"])` | `psygnal.Signal(object, object)` |
| `event.connected` | `signal._iter_slots()` or psygnal equivalent |

### Bottleneck removal summary

| Bottleneck | Solution |
|---|---|
| `_trigger_maker` exec() + sys._getframe() | `inspect.Signature` runtime validation |
| Three sequential callback collections | psygnal-style connection management + kwarg wrappers |
| No weakref tracking (listener leaks) | `weakref=True` default with kill-switch |
| No async dispatch | psygnal is internally async-ready; 2.5 uses sync dispatch, 3.0 enables async |
| No throttling/debouncing | `Event.throttle(interval)` / `Event.debounce(interval)` context managers |
| No numpy mutation detection | psygnal `EventedObjectProxy` (3.0 feature) |
