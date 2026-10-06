"""What each stage of a job costs, so the bar can mean something.

Every progress fraction in this application used to be a number somebody typed. They
were plausible and they were wrong in the one way that matters: the instrument
comparison reported **0.9 before its most expensive stage had started**, so the bar
raced to ninety per cent and then sat there for half the job. A bar that lies in that
direction is worse than no bar, because the user concludes it has hung.

So a job declares *what it costs* and the fractions are arithmetic.

### The measurements behind the weights

X0R-1403, 2026-10-05, from `tools/stage_profile.py` on synthetic six-stem pairs at 44.1k
stereo, CPU. Two lengths, to check the shares hold rather than assuming they do:

| stage | 30 s of audio | 210 s of audio |
|---|---:|---:|
| measuring your instruments | 4.94 s (31%) | 25.25 s (26%) |
| measuring the reference's | 3.20 s (20%) | 23.57 s (24%) |
| re-reading the audio | 0.05 s | 0.33 s |
| the character pass | 7.85 s (49%) | 49.60 s (50%) |
| **the comparison itself** | **0.00 s** | **0.00 s** |
| total | 16.04 s | 98.75 s |

Three things came out of that, all of which this module exists to encode:

1. **The dials are free.** Every suggestion in the application, across six instruments,
   computes in under 10 ms. The whole wait is measurement. "Comparing them" was the
   label on 50% of the job and none of the work.
2. **Half the job is the vocal.** Of the character pass's 49.6 s, **39.7 s is the vocal
   alone** - pYIN for voicing and `yin` for pitch, on both sides. The other five stems
   cost about 2 s each. This is why `X0R-1403` had to come before any optimisation: the
   target is one stem, not six.
3. **It scales with the song.** 16.04 s at 30 s and 98.75 s at 210 s is 0.47x real time,
   near enough linear. So no fixed estimate in seconds can be right, which is what
   `SECONDS_PER_SECOND_OF_AUDIO` is for.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Wall clock per second of audio, for a two-sided instrument comparison on CPU.
#: 98.75 s / 210 s = 0.470; 16.04 s / 30 s = 0.535. The longer figure is the one a user
#: feels, so the lower of the two would flatter the estimate - this is the mean, and it
#: is approximate on purpose. An estimate that pretends to two decimal places invites
#: somebody to hold it to them.
SECONDS_PER_SECOND_OF_AUDIO = 0.5


@dataclass(frozen=True, slots=True)
class Stage:
    """One stretch of work, its cost relative to the others in the same plan.

    `weight` is in whatever unit the plan likes - the measured seconds themselves read
    best, because then the table in a docstring and the code say the same thing.
    """

    key: str
    message: str
    weight: float


class Plan:
    """A job's stages, in order, with the fractions derived from the weights.

    `at(key)` is the fraction **complete when that stage begins** - that is, the sum of
    everything before it. Reporting the start rather than the end is the whole point: it
    is the only one of the two that cannot claim work that has not happened.

    The consequence is that the first stage reports 0.0, which looks like nothing is
    happening. That is handled where it should be, on the screen, by a moving indicator
    and by the stage's own words - not by inventing a fraction here.
    """

    def __init__(self, *stages: Stage) -> None:
        self.stages = stages
        total = sum(s.weight for s in stages) or 1.0
        running = 0.0
        self._at: dict[str, float] = {}
        self._message: dict[str, str] = {}
        for stage in stages:
            self._at[stage.key] = running / total
            self._message[stage.key] = stage.message
            running += stage.weight

    def at(self, key: str) -> float:
        return self._at[key]

    def message(self, key: str) -> str:
        return self._message[key]

    def report(self, handle, key: str) -> None:
        """Tell the job where it is, in one call, so a stage cannot drift from its label."""
        from app.jobs.store import JobState

        handle.update(JobState.RUNNING, self.at(key), self.message(key))


# --- the instrument comparison ---------------------------------------------------------
#
# Weights are the 210 s column above, in seconds, because that is the length of a song
# somebody actually brings. The character pass carries the re-read with it: 0.33 s is not
# a stage, it is a rounding error wearing one.

COMPARE_BOTH_SIDES = Plan(
    Stage("mine", "measuring your instruments", 25.25),
    Stage("theirs", "measuring the reference's", 23.57),
    Stage("character", "tracking the vocal's pitch, and how often each part plays", 49.93),
)

#: From a saved profile the reference half is a dictionary lookup, so its 23.57 s is gone
#: and the two remaining stages are re-weighted against each other rather than against a
#: total that no longer applies. A `Plan` normalises by its own stages, which is why this
#: is a second plan and not a flag.
COMPARE_FROM_PROFILE = Plan(
    Stage("mine", "measuring your instruments", 25.25),
    Stage("theirs", "reading the saved reference", 0.01),
    Stage("character", "tracking the vocal's pitch, and how often each part plays", 49.93),
)


def estimate_seconds(duration_s: float, both_sides: bool) -> float:
    """Roughly how long a comparison will take on a song this long.

    The reference half is a little under half the work, so a profile saves about that.
    Rough is the honest word: this is a CPU measurement from one machine, and it is used
    to set an expectation, not to make a promise.
    """
    if duration_s <= 0:
        return 0.0
    share = 1.0 if both_sides else 1.0 - (23.57 / 98.75)
    return duration_s * SECONDS_PER_SECOND_OF_AUDIO * share
