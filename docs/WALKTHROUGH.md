# extract0r studio — walkthrough narration

The script for the guided tour in the help panel. Each scene is timed at roughly
seven seconds, which is what the tour allows before it advances.

It lives here as well as in `help.js` so it can be handed to a voice actor or a
text-to-speech service without anyone having to read it out of a source file.
Recorded audio is **not** part of the app today — the tour is captioned only.

## 1. What this does

Give it a song of yours, and a song you wish yours sounded like. It pulls both apart into their separate instruments, compares them one by one, and tells you what that other song does differently.

## 2. Both at once

Drop them both on the first screen. Splitting is the slow part — roughly the length of each song, once — so it happens in a single pass rather than making you come back and wait a second time.

## 3. Six instruments, twice

Each song becomes vocals, drums, bass, guitar, piano and whatever is left. Yours and theirs, so every instrument has a counterpart to be measured against.

## 4. What the other song does differently

One card per instrument, closed to begin with, each summed up in a sentence. Open one and every difference is its own row: the measurement, what it means, and a control set to a suggested value.

## 5. A nudge, not a copy

Every suggestion is part of the measured gap, never all of it. Two records are not two takes of one arrangement, and closing the gap completely gives you a master that no longer sounds like your song. You see both numbers and decide.

## 6. Hear it before you render it

Move a control and it is audible straight away — no waiting for a master. Each side plays from its own busiest stretch, because two songs reach their choruses at different points. Twelve seconds, then it stops itself.

## 7. Then the whole mix

Once the instruments sit right, the finished mix gets compared as a whole for the last moves — tone, weight, width, loudness. That stage is deliberately separate: tone is a thing to match, arrangement is a thing to keep.

## 8. Export

Press Master. It renders the whole chain and hands you an MP3, named after your song. Nothing from the reference ends up in the file — it is measured, never sampled.
