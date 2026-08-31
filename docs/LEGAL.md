# Copyright posture and compliance checklist

**Not legal advice.** This documents the design decisions and what still needs a lawyer
(X0R-604). Nothing here is a substitute for that review.

## The actual exposure

Extract0r touches copyright at four points, and they are not equivalent:

| Step | What is created | Who holds rights |
|---|---|---|
| Separating a recording | A derivative of the **sound recording** | Label / recording owner |
| Transcribing to tab | A derivative of the **musical composition** | Publisher / songwriter |
| Mastering to a reference | Analysis only — no reference audio in the output | Reference stays untouched |
| Mixdown export | A derivative of the sound recording | Label / recording owner |

The composition right is the one people forget. Published tablature of a copyrighted song
is a derivative work of the composition, which is why sites like Ultimate Guitar license
from publishers. Private transcription for study is a different matter from distribution —
but "different" is not "safe", and fair use is a defence, not a permission.

## Design decisions that reduce exposure

**Not a catalogue.** No search across uploads, no sharing between users, no library.
Extract0r processes a file for the person who uploaded it and then deletes it. It is a
tool, closer to a DAW plugin than to a content site.

**The attestation is a server-side gate.** `REQUIRE_RIGHTS_ATTESTATION=true` makes the
API return `403` without both affirmations, regardless of what the client sent. Enforced
in `routes_tracks.upload_track` and covered by a test.

**Short retention, actually enforced.** Track folders are purged on boot and on demand
(`DELETE /tracks/{id}`); the sweep is tested by ageing a directory and asserting removal.
Scheduled sweeping is X0R-605.

**Provenance travels with the output.** Every `.x0r` carries the source SHA-256, both
backend versions, the attestation, and the copyright notice.

**No DRM circumvention.** The terms refuse audio obtained by breaking DRM or a streaming
service's terms. Extract0r accepts files, never URLs — there is no ripper in it, and there
should never be one.

**One source of copy.** `services/api/app/legal.py` holds every notice; the API serves it
and the web app renders it. A wording change is one reviewable diff, not a hunt across
templates.

## Before accepting uploads from anyone but yourself

- [ ] **X0R-604** — lawyer reviews terms, privacy, and DMCA copy for your jurisdiction
- [ ] Register a DMCA agent with the US Copyright Office if you take third-party uploads
- [ ] Set `DMCA_CONTACT_EMAIL` to a monitored address
- [ ] Publish a privacy policy matching the real retention window (X0R-607)
- [ ] Takedown workflow with an audit trail (X0R-606)
- [ ] Repeat-infringer policy, with the counter you need to enforce it
- [ ] Rate limiting, so the site cannot be used as bulk infrastructure (X0R-206)
- [ ] Remove the "written by engineers" banner from the terms page — **only** after review

## Deliberately not built

- Any download-from-URL feature. It converts a processing tool into a ripper.
- Public galleries or sharing of processed output.
- Retaining audio longer than the retention window "for quality improvement".
- Training models on user uploads.
