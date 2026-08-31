# ADR-0001 — Two services: Python for audio, Next.js for the web

**Status:** accepted · 2026-08-31

## Context

The product needs modern web UX and a serious audio/ML pipeline. Demucs, basic-pitch,
librosa, and matchering are all Python, and the mature alternatives in other ecosystems
either do not exist or wrap the Python ones anyway.

## Decision

Two deployables: a Next.js 15 app (App Router, React 19, TypeScript, Tailwind v4) and a
FastAPI service. Next rewrites `/api/*` to the API origin so the browser sees one host and
CORS stays simple in dev.

## Alternatives rejected

- **Everything in Node**, shelling out to Python for the ML. The seam still exists but is
  now undocumented and untyped, and the job/progress plumbing gets written twice.
- **Everything in Python**, server-rendered templates. Loses the interactive mixer, which
  Phase 2 is built around.
- **A .NET orchestration API in front of the Python worker.** Defensible for a team with
  .NET operational depth — but for a single-developer project it is a third deployable,
  a third test suite, and an extra network hop for no capability gained.

## Consequences

- Two toolchains, two Dockerfiles, two test commands.
- Types are duplicated across the boundary (`app/api/schemas.py` ↔ `lib/types.ts`).
  Acceptable at this size; generate from `/openapi.json` when it starts drifting.
