# ADR-0004 — A JSON session container (`.x0r`), not just text files

**Status:** accepted · 2026-08-31

## Context

A `.txt` tab is what a player prints, but it is lossy: exact timings, confidences, the
solved fingerings, and how the file was produced are all gone. Reopening a session, or
letting a user correct a note (X0R-408), needs the structured data.

## Decision

Export `.x0r`: a versioned JSON document holding provenance, per-stem note events with
timings and confidences, the solved shapes, the tuning, and the rendered ASCII tab.

JSON rather than a binary format because it stays diffable, inspectable, and trivially
readable from any language — the format is for portability, not obfuscation.

## Consequences

- `schema_version` must be checked on import (X0R-506) and bumped on breaking changes.
- The file embeds the copyright notice and the uploader's rights attestation, so provenance
  travels with the artifact.
- Larger than a `.txt`, and it duplicates the rendered tab. Worth it — the render is what
  makes the file useful without a parser.
