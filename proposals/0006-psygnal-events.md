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

Replace HyperSpy's 10-year-old custom event system (`hyperspy/events.py`) with a psygnal-backed implementation that eliminates the fragile `exec()`-based trigger generation and adds psygnal-native APIs (`emit()`, `blocked()`, `__call__()`). The `Event` class now subclasses `psygnal.SignalInstance` directly, providing both the native psygnal API and a deprecated legacy shim (`trigger()`, `suppress()`, `connect(kwargs=...)`, `suppress_callback()`). The old `Events` container class is replaced by `psygnal.SignalGroup` subclasses with `EventSignal` factory descriptors. In HyperSpy 2.5, all internal HyperSpy code (78 `emit()` sites, 10 `blocked()` sites, 0 remaining legacy calls) has been migrated to the new API. Weak references are available as an opt-in feature via `weakref=True` kwarg or `HS_EVENT_WEAKREF=1` env var, with listener auto-disconnect for bound methods. In HyperSpy 3.0, the old API surface is removed and `psygnal.Signal` becomes the public API.

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

Rewrite `hyperspy/events.py` as a psygnal-backed implementation. The `Event` class now subclasses `psygnal.SignalInstance` directly, the old `Events` container class is replaced by `psygnal.SignalGroup` subclasses using `EventSignal` factory descriptors, and the legacy (`trigger()`, `suppress()`, `suppress_callback()`, `connect(kwargs=...)`) API is preserved as a deprecated shim emitting `VisibleDeprecationWarning`.

The migration is a single coherent change with three concerns:

1. **psygnal integration** — rewrite `events.py` to subclass `psygnal.SignalInstance` for connection management and dispatch. The `EventSignal` factory returns a `psygnal.Signal` descriptor configured with `signal_instance_class=Event`. The old `Events` dynamic container is replaced by `psygnal.SignalGroup` subclasses declared statically. Weakref connections are opt-in via `weakref=True` kwarg or `HS_EVENT_WEAKREF=1` env var.
2. **Eliminate `exec()`** — remove `_trigger_maker`, reimplement `arguments=` validation with `inspect.Signature`-based runtime validation at both construction time and emit time. `Event.emit()` has custom dispatch logic: 3-group slot ordering (all → some → map), positional-to-keyword argument mapping.
3. **psygnal-native dual API + deprecation** — add `emit()`, `blocked()`, `__call__()` (inherited from `SignalInstance`) as the preferred API. Migrate all 78 internal `trigger()` calls to `emit()`, all ~30 `connect(fn, [])` to `connect(fn)` (with lambda wrappers where needed), all 4 `connect(fn, {dict})` to explicit lambda wrappers, all ~9 `suppress()` to `blocked()`, and the 1 `suppress_callback()` to the guard-flag pattern. The old API stays as deprecated shim with `VisibleDeprecationWarning`.

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
- All existing tests pass: `test_events.py` (47 tests), `test_events_performance.py` (3 benchmarks), `test_interactive.py`, `test_figure.py`, `test_widget.py`, `test_parameter.py`, `test_samfire.py`, and the full test suite.
- Every current behavior is preserved: `ValueError` on duplicate connect, `ValueError` on disconnect-not-connected, `.connected` set property, exception-abort semantics (one failing callback aborts remaining dispatch), `EventSuppressor`, `arguments=` validation, `kwargs="auto"` mode, `__deepcopy__`.
- HyperSpy's Enthought `traits` system (used for GUI configuration) is completely separate and unaffected.

### Breaking (weakref — opt-in only)

Weakref connections are **opt-in**, not default-on. Users must explicitly pass `weakref=True` or set `HS_EVENT_WEAKREF=1`. The default behavior (strong refs) is unchanged. This is less aggressive than the originally proposed default-on approach — avoids breaking downstream code that relies on the event keeping bound methods alive.

### Breaking (3.0 — future PR)

In HyperSpy 3.0, the old API surface is removed:

- `Event`/`EventSuppressor` → psygnal `Signal`/`SignalGroup` (the `Events` container class is already removed in 2.5).
- `trigger()` → `emit()`.
- `suppress()` → `blocked()`.
- `connect(kwargs=...)` → `connect()` with explicit wrapper functions.
- `arguments=` parameter → psygnal type-annotated Signals.
- `weakref` parameter added (not present in 2.5).
- `EventSignal` factory → psygnal `Signal` (17 remaining instances annotated with `# replace EventSignal with psygnal.Signal`).
- `_trigger_maker` already removed.

Downstream packages get a full 2.5 release cycle with deprecation warnings to migrate.

### Effort

| Concern | Effort | Description |
|---|---|---|
| psygnal integration | Large | Rewrite events.py to subclass SignalInstance, EventSignal factory descriptors, psygnal.SignalGroup containers, preserve all behaviors, regression tests |
| Eliminate exec | Medium | Replace `_trigger_maker` with `inspect.Signature` validation (construction + emit time), perf benchmarks |
| Dual API + deprecation | Large | Add emit()/blocked() (inherited from SignalInstance), migrate 78 trigger + ~30 connect([]) + 4 connect({}) + ~9 suppress + 1 suppress_callback, enable VisibleDeprecationWarning, 47 tests + 3 benchmarks, changelog, 3.0 migration guide |
| Total | XL | 22 files changed, 926-line events.py, all verification passed |

### Affected repos

| Repo | Changes |
|---|---|
| `hyperspy/hyperspy` | `events.py` rewrite (926 lines), `pyproject.toml` (psygnal>=0.11 + warning filters), `conda_environment*.yml`, 22 production files (call-site migration: 78 emit, 10 blocked, 59 connect), `tests/test_events.py` (47 tests), `tests/test_events_performance.py` (3 benchmarks), `upcoming_changes/`, `doc/user_guide/events_migration.rst` (3.0 roadmap, 287 lines) |

## Scope

### What's included

- `hyperspy/events.py` rewritten as psygnal-backed implementation (926 lines) — `Event` subclasses `psygnal.SignalInstance`, `EventSignal` factory produces `psygnal.Signal` descriptors, `EventSuppressor` public API preserved.
- The old `Events` dynamic container class removed — replaced by `psygnal.SignalGroup` subclasses (declared statically in each module).
- `psygnal>=0.11` added as hard dependency in `pyproject.toml`, `conda_environment.yml`, `conda_environment_dev.yml`.
- `_trigger_maker` `exec()` + `sys._getframe()` eliminated — replaced with `inspect.Signature`-based runtime validation at both construction time (`EventSignal` factory) and emit time (`_validate_emit_kwargs`).
- `Event.emit()` has custom dispatch logic: 3-group slot ordering (all → some → map), positional-to-keyword argument mapping, single-positional-arg-to-`obj` convention.
- `max_listeners` parameter on `Event` instances for leak detection (emits `VisibleDeprecationWarning` when limit exceeded).
- Psygnal-native API: `Event.emit(*args)`, `Event.__call__(*args)`, `Event.blocked()` (all inherited from `SignalInstance`).
- Opt-in weakref connections via `weakref=True` kwarg or `HS_EVENT_WEAKREF=1` env var. For `kwargs="all"`, psygnal's native `WeakMethod` handles auto-disconnect. For `kwargs=list`/`dict`, `_WeakListWrapper`/`_WeakDictWrapper` classes hold `WeakMethod`.
- `VisibleDeprecationWarning` on all deprecated methods: `trigger()`, `suppress()`, `suppress_callback()`, `connect(kwargs=...)` (non-`"all"`), `arguments=`.
- All 78 internal `trigger()` calls migrated to `emit()` across 22 production files.
- All ~30 `connect(fn, [])` calls migrated to `connect(fn)` (with lambda wrappers where the callback does not accept `**kwargs`/`*args`).
- All 4 `connect(fn, {dict})` dict-rename calls migrated to explicit `connect(lambda obj: fn(widget=obj))` wrappers.
- All ~9 `suppress()` calls migrated to `blocked()` (10 sites across 6 files after migration).
- The 1 `suppress_callback()` call migrated to the guard-flag pattern (`model.py`).
- 3.0 migration roadmap document in `doc/user_guide/events_migration.rst` (287 lines) with guard-flag pattern example.
- 47 regression tests in `test_events.py` covering emit/blocked/call-alias/deprecation-warnings + 14 weakref-specific tests.
- Performance benchmarks in `test_events_performance.py` (3 active benchmarks).
- Changelog entries in `upcoming_changes/`.
- 17 `EventSignal` instances annotated with `# in HyperSpy 3.0, replace EventSignal with psygnal.Signal` for the 3.0 migration.

### What's explicitly NOT included

- Changes to any downstream consumer files — the old API is preserved as deprecated aliases.
- Changes to `hyperspy/api.py` `__all__` exports.
- Changes to Enthought `traits` usage (separate system, unaffected).
- Introduction of `async`/`await` in any consumer code — 2.5 is synchronous-only.
- Weakref as default — weakref is opt-in only. The originally proposed `weakref=True` default with `HS_EVENT_WEAKREF=0` kill-switch was not implemented.
- `Event.throttle()`/`Event.debounce()` context managers — removed in favor of `@psygnal.throttled`/`@psygnal.debounced` decorators on individual callbacks.
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
hyperspy/events.py (new, 926 lines)
├── EventSignal(*types, description, arguments) — FACTORY FUNCTION
│   └── Returns psygnal.Signal descriptor with signal_instance_class=Event
│       Used as class attributes on psygnal.SignalGroup subclasses
│   └── Builds inspect.Signature from legacy arguments= for type validation
├── Event(SignalInstance) — psygnal subclass
│   ├── __init__(signature, doc, arguments, instance, name, ...)
│   ├── emit(*args, **kwargs) — OVERRIDES psygnal: custom dispatch
│   │   ├── Positional→keyword mapping (zip with _arguments or "obj" convention)
│   │   ├── Guard: _is_blocked (psygnal) + _suppress (legacy flag)
│   │   └── Three-group dispatch: "all" slots → "some" wrappers → "map" wrappers
│   ├── trigger(*args, **kwargs) — DEPRECATED: delegates to emit()
│   ├── blocked() — INHERITED from SignalInstance (counter-based, nestable)
│   ├── suppress() — DEPRECATED: delegates to _suppress flag context manager
│   ├── connect(function, kwargs="all", *, weakref=None, **psygnal_opts)
│   │   ├── kwargs="all" → passes all emit kwargs (passthrough)
│   │   ├── kwargs="auto" → inspects function signature
│   │   ├── kwargs=["a","b"] → filters kwargs
│   │   ├── kwargs={"a":"b"} → remaps kwargs (dict-rename)
│   │   ├── kwargs=[] → calls function() with no args (empty wrapper)
│   │   └── weakref=True → opt-in WeakMethod for bound methods, _WeakListWrapper/_WeakDictWrapper for filtered paths
│   ├── disconnect(function) — removes wrapper, raises ValueError if not found
│   ├── suppress_callback(function) — DEPRECATED: stays functional
│   ├── connected property — iterates _slots, returns originals, filters dead wrappers
│   └── __deepcopy__ — new Event with no connections
├── _WeakListWrapper / _WeakDictWrapper — WeakMethod-holding callable classes
├── EventSuppressor (composite — public API preserved)
│   ├── add(Event|SignalGroup|(Event,callback)|(SignalGroup,callback))
│   └── suppress() — enters all context managers simultaneously
└── Container: psygnal.SignalGroup subclasses (replaces old Events class)
    └── Static class attributes using EventSignal descriptors
```

**Key architectural decisions:**

- `Event` **subclasses** `psygnal.SignalInstance` — not just wraps it. All native psygnal methods (`emit`, `blocked`, `block`, `unblock`) are available. The `emit()` method is overridden to add legacy dispatch semantics.
- `EventSignal` is a **factory function**, not a class. It returns `psygnal.Signal(...)` with `signal_instance_class=Event` and `check_nargs_on_connect=False`. This avoids psygnal descriptor subclassing issues.
- The old `Events` container class is **removed**. Dynamic event registration (`__setattr__`/`__getattr__` magic) is replaced by static `psygnal.SignalGroup` subclasses with `EventSignal` descriptors.
- No `_signal` dormant field — `EventSignal` IS the `psygnal.Signal` descriptor. The `Event` instance is the runtime object.
- `emit()` has custom dispatch logic (3-group ordering: all → some → map). It does not delegate to psygnal's `_run_emit_loop` because legacy HyperSpy code depends on specific dispatch order and exception-abort semantics.
- `inspect.Signature` validation happens at two stages: construction time (in `EventSignal` factory, building parameters from `arguments=`) and emit time (in `_validate_emit_kwargs`, binding and applying defaults).

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

### weakref opt-in (implemented)

Weak references are opt-in via `weakref=True` kwarg or `HS_EVENT_WEAKREF=1` env var:

```python
class Event:
    def _resolve_weakref(self, weakref):
        """Resolve the weakref tri-state into a boolean."""
        if weakref is not None:
            return bool(weakref)
        return os.environ.get("HS_EVENT_WEAKREF", "0").lower() in ("1", "true", "yes")

    def connect(self, function, kwargs="all", *, weakref=None, **psygnal_opts):
        weakref = self._resolve_weakref(weakref)
        # ...
        if kwargs == "all":
            if weakref and inspect.ismethod(function):
                super().connect(function, unique="raise", **psygnal_opts)
                # Do NOT store in _connected_originals or _slot_mode —
                # psygnal's native WeakMethod handles the slot lifecycle
            else:
                super().connect(function, **psygnal_opts)
                self._connected_originals.add(function)
                self._slot_mode[function] = "all"
```

For `kwargs=list`/`dict` with weakref=on, wrapper classes hold `WeakMethod`:

```python
class _WeakListWrapper:
    def __init__(self, function, kwarg_list):
        self._ref = weakref.WeakMethod(function)
        self._kwarg_list = tuple(kwarg_list)
    def __call__(self, **kw):
        fn = self._ref()
        if fn is None:
            return
        fn(**{k: kw.get(k) for k in self._kwarg_list})
```

Non-weakrefable callables (lambdas, module functions) silently fall back to strong ref.

### arguments= validation without exec (implemented)

Two-stage validation replaces the old `exec()`-based `_trigger_maker`:

```python
# Stage 1: EventSignal factory — build Signature for psygnal type checking
def EventSignal(*types, description="", arguments=None, **kwargs):
    if not types and arguments:
        params = [Parameter(
            a[0] if isinstance(a, (tuple, list)) else a,
            Parameter.KEYWORD_ONLY,
            default=a[1] if isinstance(a, (tuple, list)) else Parameter.empty
        ) for a in arguments]
        types = (Signature(params),)
    return psygnal.Signal(*types, signal_instance_class=Event, ...)

# Stage 2: Event._validate_emit_kwargs — runtime validation at emit time
class Event(SignalInstance):
    def _validate_emit_kwargs(self, kwargs):
        if self._arguments is not None:
            sig = Signature([...])  # build from _arguments
            bound = sig.bind(**kwargs)
            bound.apply_defaults()
            return dict(bound.arguments)
        return kwargs
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
| `obj.events.data_changed.emit(obj=self)` | `obj.data_changed.emit(self)` |
| `obj.events.data_changed.connect(f)` | `obj.data_changed.connect(lambda *a, **kw: f(**kw))` (or native) |
| `obj.events.data_changed.connect(f, kwargs={"obj": "widget"})` | `obj.data_changed.connect(lambda obj: f(widget=obj))` |
| `with obj.events.data_changed.blocked():` | `with obj.data_changed.blocked():` |
| `with obj.events.data_changed.suppress_callback(f):` | Guard-flag pattern (callback checks own flag) |
| `EventSignal(object, arguments=["obj", "value"])` | `psygnal.Signal(object, object)` |
| `event.connected` | `signal._iter_slots()` or psygnal equivalent |
| `psygnal.SignalGroup` subclass with `EventSignal` descriptors | `psygnal.SignalGroup` subclass with `psygnal.Signal` descriptors |

### Bottleneck removal summary

| Bottleneck | Solution |
|---|---|
| `_trigger_maker` exec() + sys._getframe() | `inspect.Signature` runtime validation (two-stage) |
| Three sequential callback collections | Slot-group dispatch: "all" → "some" → "map" ordering |
| No async dispatch | psygnal is internally async-ready; 2.5 uses sync dispatch, 3.0 enables async |
| No numpy mutation detection | psygnal `EventedObjectProxy` (3.0 feature) |
