# ADR-0002 — The domain layer takes no third-party dependencies

**Status:** accepted · 2026-08-31

## Context

Demucs, TensorFlow, and torch are multi-gigabyte installs that are awkward on Windows and
slow in CI. If the tab engine imported them transitively, nothing could be tested without
them.

## Decision

`app/domain/` — notes, the fretboard solver, both tab renderers, the `.x0r` writer — imports
only the standard library. Everything heavy sits behind a `Protocol` in
`app/services/*/base.py` with a real implementation and a stub.

## Consequences

- The full test suite runs on a bare Python install in seconds; CI never installs the ML
  extras.
- The stub backends make the API and the front end developable with no models present, and
  the stub transcriber is seeded so tab output is deterministic under test.
- Cost: every backend is written twice, and the stub must be kept honest about the contract
  or tests pass against a fiction.
