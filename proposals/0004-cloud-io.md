---
proposal: 0004
title: "Cloud I/O — read and write .hspy/.zspy files from cloud storage"
type: Feature
target_branch: hyperspy/hyperspy:RELEASE_next_minor
target_repos: [hyperspy/hyperspy]
status: review
ai_assisted: true
created: 2026-07-02
---

# Cloud I/O: Read and Write .hspy/.zspy Files from Cloud Storage

## Summary

Add cloud storage support to HyperSpy so users can read `.hspy` and `.zspy` files directly from S3, GCS, Azure, and other fsspec-backed filesystems using URL syntax (`hs.load("s3://bucket/file.hspy")`), and save `.zspy` files to cloud storage. Cloud reads default to lazy mode for efficient chunked access. All changes are additive in HyperSpy's I/O layer; no changes needed in RosettaSciIO.

## Problem

HyperSpy users working with large datasets increasingly store data in cloud object storage (S3, GCS, Azure Blob, HPC filesystems via SSH). Today, they must:

- **Download files locally before loading.** A 50 GB `.zspy` dataset on S3 must be fully transferred to local disk before `hs.load()` can touch it.
- **Manually configure cloud access.** Users write their own `s3fs`/`fsspec` code to create file handles and pass them to `hs.load()`, with no standard pattern or documentation.
- **No cloud save path for `.zspy`.** Zarr natively supports cloud storage, but HyperSpy's `s.save()` doesn't know how to create cloud stores.

Ecosystem-standard tools (xarray, satpy, zarr-python) already support cloud URLs via `fsspec`. HyperSpy should too.

## Proposed approach

Use [fsspec](https://filesystem-spec.readthedocs.io/) — the ecosystem-standard filesystem abstraction — to add cloud URL support to HyperSpy's I/O layer:

1. **URL detection**: `_is_cloud_url(filename)` detects cloud URLs (`s3://`, `gs://`, `az://`, `abfs://`, `ssh://`, `http://`, `https://`).
2. **Zarr store creation**: `fsspec.get_mapper(url)` returns a `MutableMapping` that RosettaSciIO's zspy reader/writer already accepts.
3. **HDF5 file handle**: `fsspec.open(url, 'rb')` returns a file-like object that `h5py.File()` can read.
4. **Additive changes**: `storage_options` parameter on `hs.load()` and `s.save()`. All existing local I/O code paths untouched.

### Why fsspec and not s3fs/h5pyd?

- **fsspec** is the ecosystem standard used by xarray, satpy, dask, pandas, and intake. It supports S3, GCS, Azure, SSH, HTTP, WebDAV, and more — all through one API.
- **h5pyd/HSDS** requires running an HSDS server — too heavy for ad-hoc cloud reads.
- **s3fs alone** solves S3 only; `fsspec` solves all cloud providers at once.

### What zspy already supports

RosettaSciIO's zspy reader/writer accepts `MutableMapping` stores. `fsspec.get_mapper()` returns an `FSMap` (a `MutableMapping` subclass), so zspy cloud I/O requires no RosettaSciIO changes.

### What hspy needs

h5py 3.x reads from file-like objects. `fsspec.open()` returns a file-like object. HyperSpy passes it through to `h5py.File()`. Cloud write is not supported for hspy (h5py cannot write to file-like objects).

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| **s3fs-only** (direct s3fs dependency) | Solves S3 only; fsspec provides one API for all providers |
| **h5pyd / HSDS** | Requires running an HSDS server; heavy for ad-hoc cloud reads |
| **Modify RosettaSciIO** | Unnecessary — fsspec's `FSMap` is already a `MutableMapping` that rsciio accepts |
| **Auto-install cloud packages** | Adds complexity and unexpected deps; users install `s3fs`/`gcsfs`/`adlfs` themselves |

## Impact

### Additive, no breakage

All changes are additive. Existing local file I/O is untouched. Cloud support is opt-in via URL syntax.

### fsspec as optional dependency

`fsspec` is added under a `[cloud]` optional extra (`pip install hyperspy[cloud]`). Not a hard dependency — imports are lazy. If `fsspec` is not installed and a cloud URL is detected, a helpful error message tells the user what to install.

### Cloud read defaults to lazy

Cloud reads default to `lazy=True` for efficient chunked access. If the user forces `lazy=False` on a cloud URL, a warning is raised.

### Scope limits

| Supported | Not supported |
|---|---|
| `.hspy` read from cloud | `.hspy` write to cloud (h5py limitation) |
| `.zspy` read and write to cloud | Binary formats (dm3, mrc, tiff, bruker, etc.) — Phase 2+ |
| fsspec-supported filesystems (S3, GCS, Azure, SSH, HTTP) | HSDS server setup or management |

### Affected repos

| Repo | Changes | Effort |
|---|---|---|
| `hyperspy/hyperspy` | URL detection, fsspec helpers, `storage_options` parameter, `load`/`save` integration | Small-Medium |
| `hyperspy/rosettasciio` | None (Phase 1 works with existing rsciio) | None |

## Scope

### What's included

- `hs.load("s3://bucket/file.hspy")` and `hs.load("s3://bucket/file.zspy")` for reading
- `s.save("s3://bucket/file.zspy")` for writing (zspy only)
- `storage_options` parameter on `hs.load()` and `s.save()` for credentials/config
- Cloud reads default to `lazy=True`
- fsspec caching via protocol chaining (`simplecache::s3://...`)
- Helpful error when fsspec or provider package is not installed
- Tests using fsspec's `MemoryFileSystem` (no real cloud credentials needed)
- User documentation

### What's explicitly NOT included

- Cloud writing for `.hspy` (h5py cannot write to file-like objects; h5pyd/HSDS out of scope)
- Cloud reading for binary formats (dm3, mrc, tiff, bruker, emd, nexus) — Phase 2+
- Mandatory fsspec dependency
- Auto-installation of cloud provider packages
- RosettaSciIO changes
- Changes to signal/model/component architecture

## References

- [xarray cloud I/O docs](https://docs.xarray.dev/en/stable/user-guide/io.html#reading-from-cloud-storage)
- [satpy readers with fsspec](https://satpy.readthedocs.io/)
- [fsspec documentation](https://filesystem-spec.readthedocs.io/)
- [h5py file-like objects](https://docs.h5py.org/en/stable/high/file.html#file-like-objects)
- [#2784](https://github.com/hyperspy/hyperspy/issues/2784) — Saving and Loading Large Datasets
- [#1804](https://github.com/hyperspy/hyperspy/issues/1804) — Discussion: Storing Big Data
- [#1978](https://github.com/hyperspy/hyperspy/pull/1978) — Making separate IO-library

## Technical design

### URL detection

```python
def _is_cloud_url(filename):
    """Return True if filename is a cloud storage URL."""
    if not isinstance(filename, str):
        return False
    if '://' not in filename:
        return False
    from urllib.parse import urlparse
    scheme = urlparse(filename).scheme
    if not scheme:
        return False
    # fsspec protocols: s3, gs, az, abfs, ssh, http, https, etc.
    import fsspec
    return scheme in fsspec.available_protocols()
```

### Zarr store creation

For zspy files, `fsspec.get_mapper()` returns an `FSMap` (a `MutableMapping` subclass) that RosettaSciIO already accepts:

```python
def _create_fsspec_store(url, storage_options=None):
    """Create a zarr-compatible MutableMapping store from a cloud URL.

    MUST use fsspec.get_mapper() which returns FSMap (MutableMapping).
    Do NOT use zarr.storage.FsspecStore — it does NOT inherit from
    MutableMapping and would break rsciio.
    """
    import fsspec
    return fsspec.get_mapper(url, **(storage_options or {}))
```

RosettaSciIO's zspy reader at `rsciio/zspy/_api.py:225,301` checks `isinstance(filename, MutableMapping)` — `FSMap` passes this check.

### HDF5 file handle

For hspy files, create a file-like object that h5py can read:

```python
def _open_fsspec_file(url, mode='rb', storage_options=None):
    """Open a file-like object from a cloud URL for h5py.File()."""
    import fsspec
    return fsspec.open(url, mode=mode, **(storage_options or {})).open()
```

### Load path integration

In `hs.load()`, before `glob.glob()`:

```python
if _is_cloud_url(filenames):
    filenames = [filenames]  # skip glob for cloud URLs
```

In `load_single_file()`, before `os.path.isfile()`:

```python
if _is_cloud_url(filename):
    if filename.endswith('.zspy'):
        store = _create_fsspec_store(filename, storage_options)
        return load_with_reader(store, ...)
    elif filename.endswith('.hspy'):
        f = _open_fsspec_file(filename, storage_options=storage_options)
        return load_with_reader(f, ...)
```

### Cloud read defaults to lazy

```python
if _is_cloud_url(filenames):
    if lazy is None:
        lazy = True
    elif not lazy:
        warnings.warn("Cloud reads default to lazy=True for efficient access.")
```

### storage_options parameter

```python
def load(filenames, storage_options=None, **kwds):
    """Load signal(s) from file(s).

    Parameters
    ----------
    storage_options : dict, optional
        Parameters passed to fsspec for cloud storage access.
        E.g., {'key': '...', 'secret': '...'} for S3 credentials.
    """
```

`storage_options` must be an explicit parameter — if passed through `**kwds` it would reach `file_reader()` and crash with unexpected keyword arguments.
