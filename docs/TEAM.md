# How this project is worked

Three roles, one loop. Set up 2026-10-01.

| Role | Who | Defined in |
|---|---|---|
| Product Manager | `product-manager` subagent | [.claude/agents/product-manager.md](../.claude/agents/product-manager.md) |
| Developer | the main Claude Code session | — |
| QA | `qa` subagent | [.claude/agents/qa.md](../.claude/agents/qa.md) |

Ryan is the stakeholder. He is not in the loop on every step, but every step is visible
to him and he can redirect at any point.

## The loop

1. **PM scopes.** Reads the backlog and the code, checks what comparable products do,
   decides what is worth building next given one developer and one QA.
2. **PM writes the sprint** to `docs/sprints/SPRINT-<n>.md` — goal, cards, acceptance
   criteria, sequencing, explicit non-goals, risks. The developer relays it to Ryan.
3. **Developer builds**, card by card, and reports each one as it lands. Questions go
   back to the PM, or to Ryan when they are product decisions rather than product
   details.
4. **QA validates once, at the end of the sprint** — not per card. Output splits two
   ways: **defects** to the developer, **suggestions** to the PM.
5. Defects are fixed and re-verified. Suggestions are triaged by the PM into this sprint,
   the backlog, or a reasoned no.

### Why QA runs once, at the end

Changed on 2026-10-01, one card into the first sprint, on evidence.

Per-card QA was tried first and cost more than it returned. A two-point card took three
QA passes; each pass ran about twenty-five minutes, and most of that was re-separating
the same audio, because nothing persists between runs and the retention sweep clears
`storage/` hourly. By the time the sprint's cheapest card had a verdict, its most
valuable card had not been started.

The findings were real — six genuine defects on the first pass, including two that would
have shipped. The problem was never the quality of the check, it was paying full setup
cost per card when the cards all touch the same screens and one pass could cover them
together.

What this gives up, and it is worth naming: a defect found at the end of a sprint has had
more code written on top of it, so attribution is harder and the fix is bigger. The
mitigation is that the developer still reports each card as it lands, so there is a
written trail of what changed when, and the sprint plan still sequences cards that touch
the same files.

A card may still be sent to QA on its own when the developer asks — a change nobody can
verify by reading, or one that has already broken twice. That is an exception the
developer justifies, not the default.

## Rules that make the loop worth running

**QA does not fix.** The instant QA edits code it stops being an independent check. It
reports; the developer fixes.

**The PM does not write application code.** It writes documents. It can read anything.

**Acceptance criteria are written so QA can verify them in a browser** without reading
source. A criterion only a developer can check is a design note, not a criterion.

**A card that QA could not verify has not passed.** "Probably fine" is a defect against
the criteria, not a pass.

**Nothing is committed until Ryan asks.** The tree stays dirty between sprints by
default — this is a standing instruction, not an oversight.

## Starting a sprint

Ask the product manager for a plan. Give it the current state: what shipped since the
last sprint, what is uncommitted, and anything Ryan has said about direction. Agents
start cold and re-derive nothing for free.

## Conventions the whole team shares

- Card ids are `X0R-####` and live in `docs/BACKLOG.md` under an epic.
- Points: 1 ≈ half a day, 2 ≈ a day, 3 ≈ two days, 5 ≈ most of a week, 8 ≈ split it.
- Sprint plans in `docs/sprints/`, QA reports in `docs/qa/`.
- The product's brief is a **nudge toward a reference, never a copy of it**. Every
  suggestion is a fraction of the measured gap. A card that closes gaps completely is
  off-brief.
- No streaming integrations, ever. See the DRM clause in
  [docs/LEGAL.md](LEGAL.md) and `STREAMING_HOSTS` in `app/services/fetch.py`.
- `profiles/` and `storage/` are local-only and gitignored. Keep it that way.
