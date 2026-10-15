# Sprint 23 — the club finish, in the app

Nobody asked for this one. Through Sprints 16-22 every remix Ryan was sent had been finished
by a script in a scratchpad: glue, soft clip, limit, land on a loudness. The app itself still
stopped at *"a sketch of the version, not a master"*, so the one step between his remix and
something he could play out was the one step he could not do himself.

---

## 1. Finish it for a club — X0R-1500

`mastering/club.py` and `POST /tracks/{id}/version/{label}/finish`, with a panel under the
version mixer.

**The chain:** glue (3 dB of range) → optional tonal match → soft clip → limit → true-peak
ceiling, with the gain solved in up to four passes so the result lands on the asked-for
loudness.

**Why a clipper before the limiter.** A limiter alone cannot make a punchy mix loud: on the
punchy VaVaVa remix, reaching -10.6 LUFS took up to 12.5 dB of gain riding on the kicks,
which flattens the punch the mix was built for. The clipper shaves the tips of the
transients instead, where a few samples cost nothing audible. On the demo, the finish to
-9.6 LUFS touched 1.6% of samples and left the limiter riding **0.14 dB on average**.

**Targets:** club (-9.5), loud (-8), gentle (-12), streaming (-14), or any loudness between
-30 and -5. It deliberately does *not* chase the reference: "Bounce" is mastered at -6 LUFS,
and a remix pushed there is squashed. The report says what the reference measures, so the
choice is informed rather than hidden.

**The tonal match never lifts above 1.5 kHz.** Cuts apply anywhere, lifts only below - on a
gritty mix the lift the curve asks for is the grinding, since distortion already puts
intermodulation up there. Checked on the demo: it lifted 60 Hz by 2.4 dB and cut 500 Hz to
2 kHz, nothing lifted above.

**It says what it cost.** Every finish reports the loudness before and after, the true peak,
how much the clipper touched and how hard the limiter worked - and warns, in words, when the
limiter averages more than 1.5 dB ("the punch is coming off"). The master is written beside
the version as `master.{label}.*`; the version itself is never overwritten.

**The clipper holds the ceiling everywhere but the array's ends**, where the resampler's step
response rings (+0.6 dB over, measured on a constant). That is why the limiter and the
true-peak check follow it, and the test asserts the interior rather than pretending the
clipper alone is a guarantee.

## 2. A version comes back with the song — X0R-1501

Found while testing: reopening a track left the mixer and the finish unavailable until the
version was bounced again, although the version was on disk the whole time. Nothing listed
them. `GET /tracks/{id}/versions` now lists what a track has - newest first, with its layers
and whether it has been mastered - and the remix page loads the newest when a song opens.

## 3. Checked

- **Tests:** the finish lands within 0.3 LUFS of four targets under the ceiling; a quieter
  target clips less; the clipper is transparent below its knee and settles on the ceiling
  above it; the report says what it cost; a bright reference cannot make a mix brighter;
  and, through the API, a version is listed, bad targets are refused, matching without a
  reference is refused, and the master is written and served.
- **In the browser,** on the demo track: finished to -9.6 LUFS (true peak -1.0, limiter
  0.14 dB average), then again to -12 with the reference's tone; reloaded the page and the
  version came back by itself.
