---
proposal: 0005
title: "Lazy Expressions — replace eager arrays with deferred computation"
type: Architecture
target_branch: hyperspy/hyperspy:RELEASE_next_minor
target_repos: [hyperspy/hyperspy]
status: review
ai_assisted: true
created: 2026-07-02
---

# Lazy Expressions: Replace Eager Arrays with Deferred Computation

## Summary

Replace eager arrays in HyperSpy core with `LazyExpression` objects that store computation parameters and compute on demand. Targets: noise variance (stored as 3 scalars instead of a full `BaseSignal`), chisq/dof (recomputed on access rather than stored), decomposition/reconstruction methods (lazy matmul instead of deep copies), model serialization (stores expressions, not materialized arrays), and SAMFire worker data (transfers expressions, not full parameter maps).

## Problem

HyperSpy stores many derived quantities as eager arrays — duplicating data that could be stored as compact "recipes" and computed on demand:

- **`Noise_properties.variance`** stored as a full `BaseSignal` (same shape as parent signal) — should be 2-3 scalars (gain factor, gain offset, correlation factor).
- **`chisq` and `dof`** stored as full navigation signals — they are deterministic functions of model + signal + variance and can be recomputed on access.
- **`get_decomposition_model()`** deep-copies the entire signal — should be a lazy matmul (`scores @ components`).
- **Model serialization** stores chisq/dof arrays and reconstructed signals — should store expressions that recompute on load.
- **SAMFire workers** receive full parameter maps and variance arrays — should receive only current-position data.

### Principle

Store the recipe, not the result. Anything that is a deterministic function of (source data + parameters) should be stored as an expression and computed on demand.

## Proposed approach

Introduce a `LazyExpression` base class that:

1. **Captures the computation recipe**: a function + its arguments, stored as references to source data (not copies).
2. **Computes on demand**: `.compute()` produces the result. `__array_function__` enables transparent NumPy interop.
3. **Detects staleness**: subscribes to `events.data_changed` on referenced sources. When source data changes, the expression is marked stale and recomputes on next access — enabling future live data processing.
4. **Serializes compactly**: stored as a self-contained expression tree with referenced arrays. Nested expressions are inlined.
5. **Supports nesting**: expressions can reference other expressions (e.g., variance depends on a lazy decomposition model).

### What changes

| Today (eager) | Proposed (lazy) |
|---|---|
| `Noise_properties.variance` = full `BaseSignal` | `LazyExpression` with 2-3 scalars |
| `chisq`/`dof` stored as signals | Recomputed on every access |
| `get_decomposition_model()` deep-copies signal | Returns lazy matmul signal |
| Model serialization stores chisq/dof arrays | Stores `LazyExpression` tree |
| SAMFire workers get full maps | Workers get self-contained expressions |

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Keep eager arrays, optimize storage** | Doesn't address the root cause — derived data is redundant by definition |
| **Use dask arrays everywhere** | Dask computes eagerly within each chunk; LazyExpression stores the recipe at a higher semantic level (model parameters, not array chunks) |
| **Remove chisq/dof from model API** | Breaking change; users expect `model.chisq` to work |
| **Build on dask.delayed** | Dask depends on pickle for serialization; LazyExpression needs custom serialization for `.hspy` file format compatibility |

## Impact

### Non-breaking

- `model.chisq` still returns a signal (now lazy-backed with transparent `.compute()`).
- `Noise_properties.variance` still accessible as before.
- Existing `.hspy` files with old eager arrays load correctly (backward compat: new HyperSpy detects format version and converts to expressions on load).
- SAMFire API and convergence behavior unchanged.

### Breaking

None. All changes are internal storage format shifts. The public API is preserved — values that were eagerly computed before are now computed on first access.

### Affected repos

| Repo | Changes | Effort |
|---|---|---|
| `hyperspy/hyperspy` | LazyExpression class, variance/chisq/dof conversion, model serialization, SAMFire worker optimization | Large |

## Scope

### What's included

- `LazyExpression` base class with `.compute()`, `__array_function__`, reference storage, nested expression support, staleness detection
- LazyExpression serialization/deserialization in `.hspy` format
- `Noise_properties.variance` as LazyExpression
- `chisq`/`dof` as lazy (recomputed on access, not serialized)
- `get_decomposition_components/scores`, `get_bss_components/scores` return lazy signals
- `Parameter.as_signal()` with `lazy_output` parameter
- Model serialization stores expressions, not materialized arrays
- SAMFire worker data optimization (expression transfer)

### What's explicitly NOT included

- External dependencies beyond dask (already in HyperSpy)
- Base class hierarchy for LazyExpression
- Breaking existing public API
- Breaking model save/load for existing files
- Breaking SAMFire convergence behavior
- Removing chisq/dof from model API
- `Parameter.map` sparse storage (handled in separate proposal)

## References

- [#3669](https://github.com/hyperspy/hyperspy/pull/3669) — Rename factors/loadings to components/scores (prerequisite terminology)
- [#3617](https://github.com/hyperspy/hyperspy/issues/3617) — `_calculate_recmatrix` compute() silently discards result
- [#3107](https://github.com/hyperspy/hyperspy/issues/3107) — Lazy Optimization/Guidelines
- [#2983](https://github.com/hyperspy/hyperspy/issues/2983) — Lazy Machine Learning and Tensor Based Approaches
- [#2108](https://github.com/hyperspy/hyperspy/issues/2108) — Lazy loading of .npz learning results
- [#2784](https://github.com/hyperspy/hyperspy/issues/2784) — Saving and Loading Large Datasets
- [#3521](https://github.com/hyperspy/hyperspy/issues/3521) — Compute navigator on saving lazy data

## Technical design

### LazyExpression base class

```python
class LazyExpression:
    """A deferred computation that stores the recipe, not the result.

    Stores a callable + args as references to source data (not copies).
    Computes on demand. Detects staleness via events.data_changed.
    Supports nested expressions (expressions referencing expressions).
    """

    def __init__(self, func, *args, name=None, sources=None):
        self._func = func
        self._args = args  # references to source data, not copies
        self._name = name
        self._result = None
        self._stale = True
        # Subscribe to data_changed on all referenced sources
        self._sources = sources or []
        for s in self._sources:
            s.events.data_changed.connect(self._invalidate)

    def compute(self):
        if self._stale or self._result is None:
            self._result = self._func(*self._args)
            self._stale = False
        return self._result

    def _invalidate(self, obj=None):
        self._stale = True

    def __array__(self):
        return np.asarray(self.compute())

    def __array_function__(self, func, types, args, kwargs):
        return func(*[a.compute() if isinstance(a, LazyExpression) else a
                       for a in args], **kwargs)
```

### Noise variance as LazyExpression

Today `Noise_properties.variance` is stored as a full `BaseSignal` of the same shape as the parent. The actual computation is `variance = gain_factor * signal**gain_offset + correlation_factor` — three scalars. Instead:

```python
class NoiseVariance(LazyExpression):
    def __init__(self, signal, gain_factor, gain_offset, correlation_factor):
        super().__init__(
            self._compute,
            signal, gain_factor, gain_offset, correlation_factor,
            sources=[signal]
        )

    def _compute(self, signal, gain_factor, gain_offset, correlation_factor):
        return gain_factor * signal.data**gain_offset + correlation_factor
```

### chisq/dof as lazy

`chisq` and `dof` are deterministic functions of (model + signal + variance). They are NOT serialized — always recomputed on access from live model state:

```python
@property
def chisq(self):
    """Chi-squared, recomputed on every access from live model state."""
    return self._compute_chisq(self.signal, self.model, self.variance)
```

### Model serialization

Model save stores the expression tree, not materialized arrays:

```yaml
# Instead of: chisq: [array of 65,536 values]
# Store: chisq_expression: {func: chisq, sources: [signal_ref, model_ref, variance_ref]}
```

On load, the expression tree is reconstructed with references to the loaded signal and model objects. This eliminates redundant serialization of derived data.

### SAMFire worker optimization

Today, SAMFire workers receive full parameter maps. With LazyExpression, workers receive self-contained expression trees:

```python
# Instead of: send full (200x300) variance array to each worker
# Send: LazyExpression(signal_slice, gain_factor, gain_offset, correlation_factor)
```

The worker computes variance only for its assigned positions. The serialization format for worker transfer is the same as model serialization — self-contained expression tree.

### Wave execution

| Wave | Tasks |
|---|---|
| Wave 1 (foundation) | LazyExpression base class, serialization |
| Wave 2 (conversion) | Variance → LazyExpression, chisq/dof → lazy, decomposition methods → lazy |
| Wave 3 (optimization) | Model serialization, SAMFire worker data |
