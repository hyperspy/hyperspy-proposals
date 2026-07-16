---
proposal: 0001
title: "hspy-spec — a metadata specification system for HyperSpy 3.0"
type: Architecture
target_branch: hyperspy/hyperspy:RELEASE_next_major
target_repos: [hyperspy/hyperspy, hyperspy/rosettasciio, hyperspy/hspy-spec]
status: review
ai_assisted: true
created: 2026-06-30
---

# hspy-spec: A Metadata Specification System for HyperSpy 3.0

## Summary

Create a standalone package (`hspy-spec`) that defines what HyperSpy metadata is (JSON Schema schemas), how it's stored in HDF5/Zarr (encoding specifications), and how it evolves (declarative migrations, merit-based field graduation). V1 ships a restructured metadata tree (Source/Detector model replacing SEM/TEM singletons), transparent migration of old files, and a streamlined v4.0 file encoding. This is a breaking change for HyperSpy 3.0 — `s.original_metadata` is removed, the metadata tree is restructured, and old files migrate automatically on load.

## Problem

HyperSpy stores metadata in `.hspy` files, but there is no specification for what that metadata looks like. The "specification" is 951 lines of Python code in RosettaSciIO's `_hierarchical.py`:

- **No validation.** You can store `beam_energy = "purple"` and it saves without complaint.
- **No compatibility checking.** You load someone's file and hope for the best.
- **The metadata structure is undocumented.** The official docs don't mention `Acquisition_instrument` — the node every IO plugin populates.
- **Electron microscopy concepts are baked into the file format layer.** ~100 lines of migration code know about `TEM`, `SEM`, `EELS`, `EDS`.
- **Metadata migrations are ad-hoc Python code.** When the tree structure changes, someone writes more Python.

This has been discussed for years ([#2095](https://github.com/hyperspy/hyperspy/issues/2095), [LumiSpy#53](https://github.com/LumiSpy/lumispy/issues/53), [#2174](https://github.com/hyperspy/hyperspy/pull/2174)).

## Proposed approach

Create a new, standalone package (`hspy-spec`) with 3 runtime dependencies (`jsonschema`, `pyyaml`, `click`) — no numpy, no h5py, no HyperSpy. It provides:

1. **JSON Schema schemas** defining what fields exist, their types, units, and descriptions.
2. **Encoding specification documents** describing how metadata is stored in HDF5/Zarr (documenting the current v3.3 encoding for reading, plus a new v4.0 encoding for writing).
3. **A Python library** that validates metadata, migrates between versions, checks file compatibility, and scaffolds new schemas.
4. **Declarative YAML migrations** replacing the ad-hoc Python migration code in RosettaSciIO.

The specification follows code rather than preceding it: fields earn their way into shared specs by being used by 2+ independent packages (graduation) or by direct proposal when a field is clearly general. This avoids the bottleneck that kills other scientific formats — over-specification and centralized approval.

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Improve the existing Python system** (add validation to `_hierarchical.py`) | Keeps domain semantics in the format layer; no schema portability; migrations remain ad-hoc Python |
| **Adopt NeXus NXDL as the schema language** | NXDL has inferior tooling vs JSON Schema; NIAC approval bottleneck for every field; designed for archival, not working format |
| **Use LinkML as the authoring format** | Adds a translation layer; JSON Schema has vastly superior tooling and ecosystem |
| **Develop inside the `hyperspy` repo** | `hspy-spec` must be usable without HyperSpy (standalone tools, other languages); separate repo enforces the independence |
| **Keep SEM/TEM singletons in V1** | Defers the breaking change but makes the migration harder later; v3.0 is the right time for structural changes |

## Impact

### Breaking API changes (HyperSpy 3.0)

| Current | New | Rationale |
|---|---|---|
| `s.original_metadata` | `s.metadata.producer` | One unified metadata tree |
| `load_original_metadata=False` | (removed) | Producer metadata always loaded lazily |
| `s.metadata.Acquisition_instrument.TEM.beam_energy` | `s.metadata.data.instrument.source.beam_energy` | Source/Detector model |
| `s.metadata.General.title` | `s.metadata.dataset.title` | Clear namespace separation |
| `s.metadata.Signal.Noise_properties` | `s.metadata.analysis.hyperspy.noise_properties` | Analysis ≠ measurement |
| `s.metadata._HyperSpy` | `s.metadata.analysis.hyperspy.internal` | Not private, just namespaced |

### File format changes

- Old files (v3.3 encoding) **load transparently** — migration runs automatically on load.
- New files use v4.0 encoding (JSON metadata, compact axes, `signals/` group).
- HyperSpy < 3.0 **cannot read** v4.0 files. `s.save("file.hspy", legacy_metadata=True)` produces v3.3 files for backward compatibility.

### Affected repos

| Repo | Changes | Effort |
|---|---|---|
| `hyperspy/hspy-spec` (new) | Schemas, library, encoding docs, migration YAML, CLI | XL (~800-1200 LOC) |
| `hyperspy/rosettasciio` | v4.0 writer, dual reader (v3.3 + v4.0), remove EM migration code | Large |
| `hyperspy/hyperspy` | Add hspy-spec dependency, wire migration, remove `original_metadata` | Medium |

### Extension packages

Extensions (LumiSpy, exspy, pyxem, kikuchipy) are **not required** to adopt hspy-spec. They can add local schemas optionally. The field lifecycle lets them add fields with zero ceremony (Stage 0: just set the value) and graduate them to shared specs when 2+ packages use them.

## Scope

### What V1 includes

- Core schema (`dataset/`, `data/`, `producer/`, `analysis/` namespaces)
- EM extension schema (Source/Detector model with `x-nexus` annotations)
- Legacy→V1 migration (declarative JSON Patch, RFC 6902)
- Encoding specs (v3.3 reader + v4.0 writer, HDF5 + Zarr)
- HyperSpy 3.0 integration (breaking API changes)
- RosettaSciIO v4.0 writer + dual reader
- Three-level governance model (global/domain/local)
- Graduation scanner + direct proposal tooling
- Pydantic v2 model generation from schemas
- Example local schemas and producer mapping reference files

### What V1 explicitly does NOT include

- NXem-compliant `.nxs` export (V2 — the `x-nexus` annotations are documentation only in V1)
- Executable conversion engine (V2 — V1's producer mappings are reference documentation)
- Automated alignment checking against external standards (V2+)
- Reverse reader mapping (`.nxs` → hspy-spec canonical fields) (V2+)
- SignalCollection API for multi-signal files (separate follow-up proposal)
- C/C++ SDK or vendor certification program (long-term ecosystem growth)

## References

- [#2095](https://github.com/hyperspy/hyperspy/issues/2095) — Discussion: Hyperspy metadata SEM vs TEM
- [LumiSpy#53](https://github.com/LumiSpy/lumispy/issues/53) — Luminescence specific metadata (includes "pandoc for metadata" vision)
- [#2174](https://github.com/hyperspy/hyperspy/pull/2174) — Split IO - RosettaSciIO
- [rosettasciio#89](https://github.com/hyperspy/rosettasciio/issues/89) — Improve metadata handling
- [#1222](https://github.com/hyperspy/hyperspy/issues/1222) — Update metadata specification
- [#2536](https://github.com/hyperspy/hyperspy/issues/2536) — Large original_metadata slowing hyperspy
- [#2913](https://github.com/hyperspy/hyperspy/pull/2913) — Deprecate setting metadata/original_metadata directly
- [#2974](https://github.com/hyperspy/hyperspy/issues/2974) — hs.load cannot load .hspy from newer version
- [#3093](https://github.com/hyperspy/hyperspy/pull/3093) — Update metadata convention (open, incomplete)
- [#3528](https://github.com/hyperspy/hyperspy/pull/3528) — Deprecate tmp_parameters
- [LumiSpy#109](https://github.com/LumiSpy/lumispy/pull/109) — LumiSpy metadata structure
- [pyxem#456](https://github.com/pyxem/pyxem/issues/456) — pyxem metadata overhaul
- [kikuchipy#466](https://github.com/pyxem/kikuchipy/issues/466) — Removing custom EBSD metadata nodes
- [NXem application definition](https://manual.nexusformat.org/classes/applications/NXem.html)
- [#2725](https://github.com/hyperspy/hyperspy/pull/2725) — Enhancement of NeXus file IO

## Technical design

### The current metadata structure (legacy)

```text
metadata/
├── General/              ← dataset info (title, authors, date)
│   └── FileIO/           ← load/save history
├── Signal/               ← signal info (signal_type, quantity)
│   ├── FFT/              ← analysis state (not measurement!)
│   └── Noise_properties/ ← analysis state (not measurement!)
├── Sample/               ← sample info
├── Acquisition_instrument/
│   ├── TEM/              ← TEM-specific (singleton — never both TEM and SEM)
│   │   ├── beam_energy
│   │   ├── Stage/
│   │   └── Detector/
│   │       ├── EELS/
│   │       └── EDS/
│   └── SEM/              ← SEM-specific (same structure, duplicated)
│       └── ...
└── _HyperSpy/            ← internal state (folding, stacking)

original_metadata/        ← separate container, raw vendor data
```

Problems: SEM and TEM are duplicate singletons. Analysis state (FFT, noise properties) is mixed with measurement metadata. `original_metadata` is a separate container with no relationship to `metadata`. The entire `Acquisition_instrument` subtree is undocumented.

### The new metadata structure (V1)

```text
metadata/
├── dataset/              ← administrative (title, authors, date, doi)
├── data/                 ← what was measured
│   └── instrument/
│       ├── source/       ← excitation (beam_energy, stage, source_type)
│       └── detector/     ← detection (detector_type, EELS/EDS/CL settings)
├── producer/             ← raw data from acquisition software (replaces original_metadata)
└── analysis/             ← what tools computed
    ├── hyperspy/         ← noise_properties, folding, file_io history
    └── lumispy/          ← LumiSpy's calibration results
```

Key changes:

| Before | After | Why |
|---|---|---|
| `Acquisition_instrument.TEM.beam_energy` | `data.instrument.source.beam_energy` | No more SEM/TEM singletons — `source_type` field distinguishes them |
| `Acquisition_instrument.TEM.Detector.EELS` | `data.instrument.detector.eels` | Detector is a sibling of Source, not nested under instrument type |
| `General.title` | `dataset.title` | Clear namespace — administrative metadata |
| `Signal.Noise_properties` | `analysis.hyperspy.noise_properties` | Analysis ≠ measurement |
| `Signal.FFT` | `analysis.hyperspy.fft` | Analysis ≠ measurement |
| `_HyperSpy` | `analysis.hyperspy.internal` | Not private, just namespaced |
| `original_metadata` (separate container) | `metadata.producer` (unified tree) | One tree, clear roles: `data/` = validated, `producer/` = raw, `analysis/` = computed |

### The Source/Detector model

Instead of `TEM` and `SEM` as separate nodes (with duplicated fields like `beam_energy` in both), V1 uses a single `source` node with a `source_type` field:

```yaml
data:
  instrument:
    source:
      source_type: TEM          # SEM, TEM, or STEM
      beam_energy: 200          # keV
    detector:
      detector_type: EELS       # EELS, EDS, EBSD, CL, Camera
      eels:
        collection_angle: 10    # mrad
```

### The v4.0 file encoding

Since old HyperSpy can't read new files anyway, V1 streamlines the HDF5/Zarr encoding:

| Aspect | v3.3 (old, kept for reading) | v4.0 (new, for writing) |
|---|---|---|
| Metadata storage | Recursive groups/attrs with prefix conventions (`_sig_`, `_list_`, `_bs_`, `_None_`) | Single JSON attr (`metadata_json`) — native types, no hacks |
| Axes storage | `axis-0`, `axis-1` groups (one per axis) | Single `axes` group with array attrs |
| Signal container | `Experiments/` (misleading name) | `signals/` with `signal_0`, `signal_1` (no name collisions) |
| `None` values | `"_None_"` string sentinel | JSON `null` (native) |
| Python type info | `_type: UniformDataAxis` (Python class name) | Inferred from fields (no `_type`) |
| Large arrays in metadata | Stored as groups with prefix conventions | Stored as datasets, referenced from JSON via `{"__dataset__": "path"}` |
| Nested signals in metadata | `_sig_` prefix convention | Stored as signal groups, referenced via `{"__signal__": "path"}` |
| Learning results | Separate group | In `metadata_json` under `analysis/` |
| Models | `Analysis/models` at file root | `signals/signal_N/models/` inside signal |
| `tmp_parameters` | Written to file | Not written (temporary by definition) |

Old files (v3.3) are fully supported for reading. New files (v4.0) are simpler, language-agnostic, and eliminate all encoding hacks.

### External standards and NeXus alignment

EM field names align with NeXus NXem. Each EM field carries an `x-nexus` annotation documenting the NXem equivalent path, units, and any transform needed (e.g., V → keV):

```text
Gatan's "HT Value": 200000 (in V)
  → mapped to NXem path: ebeam_column.electron_source.voltage
  → hspy-spec's x-nexus annotation: data.instrument.source.beam_energy ← NXem path
  → transform: divide by 1000 (V → keV)
  → result: data.instrument.source.beam_energy = 200 (in keV)
```

External standards serve as the intermediate representation for format conversion (the "pandoc for metadata" vision). V1: `x-<standard>` annotations are documentation (the foundation). V2: they become an executable conversion engine.

### Role distinction: `.hspy` vs `.nxs`

- `.hspy`/`.zspy` is the **working/analysis format** — flexible, validated, tool-friendly, supports all HyperSpy features.
- `.nxs` is the **archival/interchange format** — standards-compliant, facility-ready, FAIR.

Data lifecycle: **acquisition → working/analysis (.hspy) → archival/publication (.nxs)**

V1 does NOT add NXem-compliant `.nxs` export — the current NeXus writer stores metadata as unvalidated `NXCollection`, not as NXem application definitions. The `x-nexus` annotations are the foundation for a future V2 NXem-compliant writer.

### Field governance: three levels

| Level | What lives here | Who approves | Example |
|---|---|---|---|
| **Global** (`hspy-spec` core) | Fields used across domains | 2+ maintainers | `dataset.title`, `data.instrument.source.beam_energy` |
| **Domain** (e.g., `hspy-spec-em`) | Fields used within a community | Domain maintainers | EELS `collection_angle` |
| **Local** (extension repos) | Fields used by one package | Package maintainers | LumiSpy's calibration method |

Two paths for adding fields:

1. **Graduation** (bottom-up): when 2+ packages independently use a field, it graduates from local to domain or global.
2. **Direct proposal** (top-down): when a field is clearly general, any developer can propose it directly.

No committee decides what matters — actual usage does.

### Producer metadata

The `producer/` namespace stores raw metadata from acquisition software (Gatan DM, Bruker BCF, JEOL ASW, Nion Swift, abTEM). Producer entries are NOT linked to canonical entries — they are independent values:

- Producer values are **immutable** — they record what the instrument reported.
- Canonical values can be **user-corrected** — if the analyst discovers the beam energy was wrong.
- **Divergence is meaningful** — it records corrections, not errors.

An optional `hspy-spec check-consistency` command flags divergences as advisory info.

### Timeline

| Phase | Target | What ships |
|---|---|---|
| Community discussion | 2-4 weeks | This proposal — community reviews, provides feedback |
| Beta1 (V1) | HyperSpy 3.0 beta1 | Schemas, migration, HyperSpy integration, v4.0 encoding, breaking API changes |
| Beta2 (V2) | HyperSpy 3.0 beta2 | Executable conversion engine, NXem-compliant `.nxs` export, alignment checking |
| Final | HyperSpy 3.0 | V1 + V2, tested through two beta cycles |
| Post-release | — | JOSS paper |

### Implementation waves

| Wave | Phase | Todos | What ships |
|---|---|---|---|
| 1 | Pre-beta1 | 1-7 | Repo, library, encoding docs, legacy reference, architecture docs, CI, pre-commit |
| 2 | Beta1 | 8-14 | Core schema, EM extension, migration, conformance tests, HyperSpy integration, Pydantic models, docs |
| 3 | Beta1 (parallel) | 15-19 | ML schema, HyperSpy analysis schema, extension onboarding, graduation scan, examples + producer mappings |
| 4 | Beta2 | 20-22 | Extract EM repo, publish hspy-spec to PyPI, update dependencies |
| 5 | Post-3.0 | 23 | JOSS paper |
