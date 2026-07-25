---
proposal: 0003
title: "MetadataView — replace DictionaryTreeBrowser with a clean container for HyperSpy 3.0"
type: Architecture
target_branch: hyperspy/hyperspy:RELEASE_next_major
target_repos: [hyperspy/hyperspy]
status: review
ai_assisted: true
created: 2026-07-02
depends_on: 0001
---

# MetadataView: Replace DictionaryTreeBrowser with a Clean Container

## Summary

Replace `DictionaryTreeBrowser` (DTB) — a 15-year-old metadata container carrying legacy design accidents — with `MetadataView`, a ~250-350 LOC class built from scratch with plain `dict` storage, no slugification, and no envelope format. In Wave 2 (gated on `hspy-spec` V1), switch the metadata namespace to the V1 structure (`dataset/`, `data/`, `producer/`, `analysis/`) and wire `hspy-spec` migration into the load path. Optional Wave 3 adds Pydantic-backed storage for type hints and IDE autocomplete.

## Problem

`DictionaryTreeBrowser` (650 LOC, `hyperspy/misc/_utils.py:204-851`) is the container underlying all HyperSpy metadata. It carries 15-year-old design accidents:

- **Envelope storage**: each value is wrapped as `{"key": value, "_dtb_value_": ...}`, adding indirection on every access.
- **`__getattribute__` override**: intercepts ALL attribute access, slugifying every name through `fnmatch.translate()`. `mv.My_Key = 1` becomes `mv._db["my_key"]` — lossy, unpredictable.
- **`add_dictionary()` re-initializes `self.__init__()`**: side-effect mutation that breaks the existing instance.
- **Iteration depends on mutable `_db_index` state**: `for key, value in metadata:` produces different results depending on internal cursor position.

DTB also does not support schema validation, has no type hints, and cannot be used for IDE autocomplete. Copying DTB's behavior into a new class for a minor release would be throwaway work — the major release would rewrite it anyway.

## Proposed approach

Build `MetadataView` from scratch in three waves:

**Wave 1 (can start immediately, no hspy-spec dependency):**

- Plain `dict` storage (`self._data`). No envelope. No slugification.
- `__getattr__` only (called when normal lookup fails), not `__getattribute__`.
- `add_dictionary()` merges via `nested_dictionary_merge()` — no `self.__init__()` re-init.
- `__iter__` returns `iter(self._data.items())` — values are raw dicts, not MetadataView.
- Same `set_item`/`get_item`/`has_item`/`add_node` signatures as DTB for familiarity.
- `as_dictionary()` must produce RosettaSciIO-compatible output (with `_sig_`, `_hspy_AxesManager_`, `_hspy_Axis_` prefixes).
- DTB is **removed entirely**. No deprecated alias.

**Wave 2 (gated on hspy-spec V1 completion):**

- Switch `_create_metadata()` to V1 namespace (`dataset/`, `data/`, `producer/`, `analysis/`).
- Wire `hspy_spec.migrate()` into the load path. Old `.hspy` files migrate transparently.
- `metadata_schemas` attr written on save. Optional schema validation.

**Wave 3 (optional, post-3.0):**

- Pydantic v2 models generated from hspy-spec schemas as optional storage backend.

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Keep DTB as-is** | No schema validation, no type hints, slugification is lossy, envelope adds indirection — incompatible with hspy-spec goals |
| **Subclass DTB and add validation** | Copies all legacy design accidents into new code; DTB's 650 LOC would grow, not shrink |
| **Copy DTB's behavior into MetadataView** | The whole point of a major release is to break cleanly — copying 15-year-old design accidents is throwaway work |
| **Adopt an external library** (e.g., `Box`, `AttrDict`) | External deps for what is essentially a 250-350 LOC class; no control over serialization format that RosettaSciIO relies on |

## Impact

### Breaking changes (HyperSpy 3.0)

| Change | Impact | Migration |
|---|---|---|
| DTB removed entirely | All code importing `DictionaryTreeBrowser` breaks | Use `MetadataView` — same signature for `set_item`/`get_item` |
| Keys stored as-is, no slugification | `mv.My_Key = 1; mv.as_dictionary()` returns `{"My_Key": 1}` | Access by original key name |
| `original_metadata` keys not slugified | `s.original_metadata["Beam Energy (keV)"]` instead of `Beam_Energy_keV` | Documented in migration guide |
| V1 namespace (Wave 2) | `s.metadata.General.title` → `s.metadata.dataset.title` | Error message points to migration path |
| Iterator values are raw dicts | `for k, v in metadata:` returns plain dicts, not MetadataView | Access via `metadata.key` for dot access |

### Non-breaking

- `set_item`/`get_item`/`has_item`/`add_node` signatures unchanged — most user code unaffected.
- `as_dictionary()` output is RosettaSciIO-compatible (same `_sig_`/`_hspy_AxesManager_` prefixes).
- RosettaSciIO encoding logic unchanged. File format structure unchanged (only `metadata_schemas` attr added).

### Affected repos

| Repo | Changes | Effort |
|---|---|---|
| `hyperspy/hyperspy` | MetadataView class, remove DTB, update all 7 call sites + tests | Large (Wave 1: ~350 LOC new, ~650 LOC removed) |
| Extension packages | Migration to V1 namespace (Wave 2) | Small (error messages point to migration path) |

## Scope

### What's included

- Clean `MetadataView` class (~250-350 LOC) with plain dict storage (Wave 1)
- DTB removed entirely from codebase (Wave 1)
- All tests updated for MetadataView (Wave 1)
- V1 namespace cutover + hspy-spec migration (Wave 2, gated on proposal 0001)
- `metadata_schemas` attr on save + optional validation (Wave 2)
- Optional Pydantic storage backend (Wave 3, post-3.0)

### What's explicitly NOT included

- Copying DTB's envelope storage, slugification, `__getattribute__` override, or `add_dictionary` re-init
- RosettaSciIO encoding changes
- `.hspy`/`.zspy` file format changes (only `metadata_schemas` attr added)
- Pydantic as hard runtime dependency
- Removing `slugify` from `_utils.py` (used by model/component for naming, not metadata)

## References

- [Proposal 0001: hspy-spec V1](https://github.com/hyperspy/hyperspy-proposals/pull/1) — prerequisite for Wave 2
- [#2536](https://github.com/hyperspy/hyperspy/issues/2536) — Large original_metadata slowing hyperspy
- [#2913](https://github.com/hyperspy/hyperspy/pull/2913) — Deprecate setting metadata/original_metadata directly
- [#3528](https://github.com/hyperspy/hyperspy/pull/3528) — Deprecate tmp_parameters
- [#1222](https://github.com/hyperspy/hyperspy/issues/1222) — Update metadata specification
- [#2095](https://github.com/hyperspy/hyperspy/issues/2095) — Hyperspy metadata SEM vs TEM

## Technical design

### MetadataView class design

```python
class MetadataView:
    """A clean metadata container with plain dict storage.

    Replaces DictionaryTreeBrowser. No envelope, no slugification,
    no __getattribute__ override.
    """

    def __init__(self, dictionary=None):
        self._data = dict(dictionary) if dictionary else {}

    def __getattr__(self, name):
        if name in self._data:
            value = self._data[name]
            if isinstance(value, dict):
                return MetadataView(value)  # wrap on access
            return value
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def __iter__(self):
        return iter(self._data.items())

    def as_dictionary(self):
        """Return deep copy with signal/axis serialization prefixes."""
        # Produces RosettaSciIO-compatible output
        ...

    def add_dictionary(self, dictionary):
        """Merge dictionary via nested_dictionary_merge.

        No self.__init__() re-init.
        """
        from hyperspy.misc.utils import nested_dictionary_merge
        nested_dictionary_merge(self._data, dictionary)
```

### Key differences from DictionaryTreeBrowser

| Feature | DTB | MetadataView |
|---|---|---|
| Storage | `{"key": ..., "_dtb_value_": ...}` envelope | Plain `dict` (`self._data`) |
| Attribute access | `__getattribute__` override on every access | `__getattr__` only when normal lookup fails |
| Slugification | All keys slugified via `fnmatch.translate()` | Keys stored as-is |
| `add_dictionary()` | Calls `self.__init__()` — re-initializes | Calls `nested_dictionary_merge()` — merges |
| Iterator | Depends on mutable `_db_index` | Returns `iter(self._data.items())` |
| Values from iter | MetadataView instances | Raw dicts |
| Lines of code | ~650 LOC | ~250-350 LOC |

### V1 namespace (Wave 2)

After hspy-spec V1 ships, `_create_metadata()` switches to:

```text
metadata/
├── dataset/              ← administrative (title, authors, date, doi)
├── data/                 ← what was measured (instrument source/detector, sample)
├── producer/             ← raw data from acquisition software
└── analysis/             ← what tools computed (hyperspy, lumispy, etc.)
```

Legacy paths (`General`, `Signal`, `Acquisition_instrument.TEM`) raise `AttributeError` with a message pointing to the V1 equivalent.

### Migration flow (Wave 2)

```text
RosettaSciIO reads legacy .hspy
  → returns legacy dict (TEM/SEM singletons, General, Signal, _HyperSpy)
  → hspy_spec.migrate() applies JSON Patch migration
  → produces V1 dict (source/detector, dataset, analysis)
  → MetadataView wraps V1 dict
  → old code that accesses metadata.General → AttributeError with migration hint
```

### Wave execution

| Wave | Depends on | Ships in |
|---|---|---|
| Wave 1 (MetadataView) | Nothing | HyperSpy 3.0 beta1 |
| Wave 2 (V1 namespace + migration) | hspy-spec V1 | HyperSpy 3.0 beta1 |
| Wave 3 (Pydantic) | hspy-spec schemas at recommendation maturity | Post-3.0 |

Wave 1 and hspy-spec development can run in parallel — Wave 1 produces a clean MetadataView with the legacy namespace; Wave 2 adds V1 namespace and migration on top.
