---
proposal: 0002
title: "hspy-spec V2 — executable format conversion and NeXus interoperability"
type: Architecture
target_branch: hyperspy/hyperspy:RELEASE_next_major
target_repos: [hyperspy/hspy-spec, hyperspy/rosettasciio, hyperspy/hyperspy]
status: review
ai_assisted: true
created: 2026-06-30
depends_on: 0001
---

# hspy-spec V2: Executable Format Conversion and NeXus Interoperability

## Summary

V2 makes the `x-<standard>` annotations from V1 executable. When you load a Gatan DM3 file, the metadata populates the canonical `data/` tree automatically — no ad-hoc Python mapping code needed. When you export to `.nxs` for a facility archive, it produces a proper NXem application definition, not a generic `NXCollection` dump. V2 also adds reverse reader mapping (`.nxs` → hspy-spec), automated alignment checking against external standards, and domain expansion beyond EM.

## Problem

V1 ships `x-<standard>` annotations as documentation — a human has to read them to understand how hspy-spec fields map to external standards like NeXus NXem. This means:

- **Producer-to-canonical population is still manual.** Each RosettaSciIO IO plugin has ad-hoc Python code that reads vendor fields and populates `Acquisition_instrument.TEM.beam_energy` from `Microscope Info.HT Value`. V1 moves this into `producer/` but doesn't automate the `producer/` → `data/` mapping.
- **NeXus export is unvalidated.** The current NeXus writer stores metadata as `NXCollection` (unstructured), not as NXem application definitions. Facilities using `pynxtools` cannot validate the output.
- **No alignment checking.** When NeXus NXem renames or restructures a field, hspy-spec has no way to detect the drift until a user reports a broken conversion.
- **No reverse mapping.** Loading a `.nxs` file populates `producer/` but leaves `data/` empty — the canonical metadata is not extracted.

## Proposed approach

V2 adds six capabilities on top of V1's foundation:

1. **Executable conversion engine** — V1's producer mapping files become executable YAML. The engine reads `x-<standard>` annotations and applies transforms automatically at load time.
2. **NXem-compliant `.nxs` export** — reads `x-nexus` annotations and builds the correct HDF5 group hierarchy for NXem application definitions.
3. **Reverse reader mapping** — `.nxs` → hspy-spec: reads NXem paths, looks up `x-nexus` annotations, applies reverse transforms, populates `data/`.
4. **Automated alignment checking** — verifies `x-nexus` annotations match the live NeXus standard; CI runs weekly or on demand.
5. **Bidirectional contribution** — generates proposal documents for contributing hspy-spec fields back to external standards.
6. **Domain expansion** — adds optical (LumiSpy), photoemission (exspy), and diffraction (pyxem) extensions.

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Keep ad-hoc Python mapping in IO plugins** | Maintains the status quo that V1 was designed to replace; no schema portability; every format change requires Python edits |
| **Build a custom IR (intermediate representation)** | The `x-<standard>` annotations already serve as the IR; a separate IR adds complexity without benefit |
| **Use NXDL as the conversion format** | NXDL is NeXus-specific; hspy-spec needs to support multiple standards (EMSA, etc.), not just NeXus |
| **Make V2 part of V1** | V1 is already XL effort; V2 depends on V1 being stable and tested through a beta cycle |

## Impact

### What V2 changes

| Component | V1 (baseline) | V2 (new) |
|---|---|---|
| Producer mapping files | Reference documentation | Executable YAML read by the engine |
| `.nxs` export | `NXCollection` (unstructured) | NXem application definition (structured, validatable) |
| `.nxs` import | `producer/` only, `data/` empty | `producer/` + `data/` populated via reverse mapping |
| Alignment checking | Manual | Automated, CI-integrated |
| Domain extensions | EM only | EM + optical + photoemission + diffraction |

### What V2 does NOT change

- JSON Schema 2020-12 in YAML remains the schema format
- Merit-based graduation governance — unchanged
- `.hspy`/`.zspy` file format and encoding rules — unchanged
- JSON Patch (RFC 6902) migration engine — unchanged
- RosettaSciIO still reads raw file formats into `producer/`; the engine populates `data/` from `producer/`

### Affected repos

| Repo | Changes | Effort |
|---|---|---|
| `hyperspy/hspy-spec` | Conversion engine, NXem writer, reverse reader, alignment checker, domain extensions | Large |
| `hyperspy/rosettasciio` | Wire conversion engine into load path; NXem export integration | Medium |
| `hyperspy/hyperspy` | API for `spec.export_to_nexus()`, reverse mapping on `.nxs` load | Small |

### Prerequisites

V2 targets HyperSpy 3.0 beta2. Before V2 implementation begins:

1. V1 is shipped in HyperSpy 3.0 beta1.
2. The community has tested V1's migration on real files during the beta period.
3. EM extension schemas have `x-nexus` annotations verified and stable.
4. Beta1 feedback identifies any conversion or alignment edge cases.
5. The community signals demand for NXem-compliant `.nxs` export, or FAIRmat/pynxtools validates the approach.

## Scope

### What V2 includes

- Executable conversion engine (producer → standard → hspy-spec)
- NXem-compliant `.nxs` export (structured application definitions)
- Reverse reader mapping (`.nxs` → hspy-spec canonical fields)
- Automated alignment checking with CI integration
- Bidirectional contribution tooling (propose hspy-spec fields to external standards)
- Domain expansion: optical, photoemission, diffraction extensions
- Extraction of EM extension to separate `hyperspy/hspy-spec-em` repository

### What V2 explicitly does NOT include

- New schema language (JSON Schema 2020-12 remains)
- New governance model (merit-based graduation unchanged)
- New file format (`.hspy`/`.zspy` encoding unchanged)
- New migration engine (JSON Patch RFC 6902 unchanged)
- Replacing RosettaSciIO (it still reads raw formats; the engine populates `data/` from `producer/`)

## References

- [Proposal 0001: hspy-spec V1](https://github.com/hyperspy/hyperspy-proposals/pull/1) — metadata specification system for HyperSpy 3.0
- [LumiSpy#53#issuecomment-814772350](https://github.com/LumiSpy/lumispy/issues/53#issuecomment-814772350) — "pandoc for metadata" vision
- [NeXus NXem application definition](https://manual.nexusformat.org/classes/applications/NXem.html)
- [FAIRmat NeXus definitions](https://github.com/FAIRmat-Experimental)
- [#2095](https://github.com/hyperspy/hyperspy/issues/2095) — Hyperspy metadata SEM vs TEM
- [rosettasciio#89](https://github.com/hyperspy/rosettasciio/issues/89) — Improve metadata handling
- [#2725](https://github.com/hyperspy/hyperspy/pull/2725) — Enhancement of NeXus file IO

## Technical design

### Executable conversion engine

V1's producer mapping files become executable YAML that the engine reads at load time:

```python
import hspy_spec

spec = hspy_spec.load()
metadata = read_metadata_from_hspy("gatan_data.hspy")

spec.convert(metadata, source="producer/gatan/dm_v3")
```

The conversion chain:

```text
producer/gatan/dm3["HT Value": 200000]       (raw, in V)
  → mapping: gatan.dm3.HT_Value → NXem.electron_source.voltage    (producer → standard)
  → x-nexus annotation: data.instrument.source.beam_energy ← NXem path  (standard → hspy)
  → transform: divide_by_1000                  (V → keV)
  → data.instrument.source.beam_energy = 200   (canonical, in keV)
```

Fields that exist in a standard but not in hspy-spec stay in `producer/` (unchanged from V1). Fields with no standard equivalent use direct producer→hspy mappings (the V1 fallback, now executable).

What this replaces: the ad-hoc Python code in IO plugins that manually populates `Acquisition_instrument.TEM.beam_energy` from `Microscope Info.HT Value`. V2's engine reads declarative YAML mappings instead.

What this does NOT replace: the IO plugin's job of reading the raw file format (BCF binary structure, DM3 tag tree, MSA text parsing). The plugin still reads raw data into `producer/`; the engine populates `data/` from `producer/`.

### NXem-compliant `.nxs` export

```python
spec.export_to_nexus(signal, "archive.nxs", definition="NXem")
```

This reads the `x-nexus` annotations from the EM extension schema and builds the correct HDF5 group hierarchy (`ENTRY` → `measurement` → `instrument` → `ebeam_column` → `electron_source` → `voltage`), applying reverse transforms (keV → V) where needed. A facility using `pynxtools` can validate the output.

Prerequisite: the EM extension must have reached stability (maturity `recommendation`, not `candidate`).

### Reverse reader mapping (`.nxs` → hspy-spec)

```python
s = hs.load("archive.nxs")
# → RosettaSciIO reads NXdata → signal
# → V2 engine reads NXem paths → looks up x-nexus annotations → applies transforms
# → populates data.instrument.source.beam_energy from ebeam_column.electron_source.voltage
# → populates data.instrument.detector.eels.collection_angle from NXem_eels paths
# → fields with no hspy-spec equivalent stay in producer/nexus/
```

This enables roundtrip: `.hspy` → `.nxs` → `.hspy` with canonical metadata preserved.

### Automated alignment checking

```bash
$ hspy-spec check-alignment --standards nexus
✅ 23 fields aligned with NXem v2027.01
⚠️  1 field diverged:
    NXem renamed: convergence_semi_angle → semi_convergence_angle
    Update x-nexus annotation in EM extension schema
ℹ️  3 new NXem fields with no hspy equivalent (candidates for adoption)
```

A standard adapter plugin reads NXDL XML and extracts field paths for comparison. CI runs this weekly (or on demand). When a standard changes a field we care about, we know about it — before a user reports a bug.

### Bidirectional contribution

```bash
$ hspy-spec propose-to-external --field em.source.working_distance --standard nexus
Created proposal document for NIAC review.
  → Suggested NX path: NXem.ENTRY.measurement.instrument.ebeam_column.working_distance
```

This is a documentation generator, not an automatic submission. It creates a proposal document with the `x-nexus` annotation data formatted for the target standard's review process.

### Domain expansion

| Extension | Domain | Key targets | NeXus alignment |
|---|---|---|---|
| `hspy-spec-optical` | CL, PL, Raman | LumiSpy | NXmpes / NXraman (when available) |
| `hspy-spec-pes` | Photoemission | exspy | NXmpes |
| `hspy-spec-diffraction` | 4D-STEM, PXRD | pyXem | NXem_img (existing) or new definition |

Each domain extension is its own repository with its own release cycle — the same pattern V1 established for `hspy-spec-em`.

### Role distinction: `.hspy` vs `.nxs`

| Aspect | `.hspy` / `.zspy` | `.nxs` |
|---|---|---|
| Purpose | Working and analysis format | Archival and interchange format |
| Flexibility | Full HyperSpy features (models, decomposition, analysis results) | Standards-compliant, restricted structure |
| Validation | Against hspy-spec schemas | Against NXem application definition |
| Target audience | Researchers doing analysis | Facilities, data repositories, cross-tool interchange |
| Metadata model | Producer → hspy-spec (flexible) | NXem (rigid) |

Data lifecycle: **acquisition → working/analysis (.hspy) → archival/publication (.nxs)**
