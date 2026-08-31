# ADR-0003 — In-process job store first, Redis later

**Status:** accepted · 2026-08-31 · superseded by X0R-702 when it ships

## Context

Separation takes minutes, so it cannot run inside a request. The obvious answer is Celery
or RQ with Redis — which means another service, another Dockerfile, and another failure
mode before there is a working product.

## Decision

Ship a `ThreadPoolExecutor` plus a dict behind `JobStore.submit(kind, track_id, work)`,
with `/api/v1/jobs/{id}` for polling. Accept that it is single-node and forgets on restart.

Because the callers only ever see `submit` and `JobHandle.update`, replacing the internals
with RQ (X0R-702) touches no route.

## Consequences

- No queue infrastructure for the MVP; progress reporting works today.
- Restarting the API loses in-flight jobs. Acceptable while the app is single-user; it is
  the trigger to do X0R-702.
- Python threads are fine here because the work is subprocess- and IO-bound, not CPU-bound
  in the interpreter.
