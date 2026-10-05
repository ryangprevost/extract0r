"""How far this tool is allowed to move a mix, as one control instead of nine constants.

Every suggestion in this application is a *fraction of a measured gap, clamped*. The
fraction is the intent - "move toward that record" rather than "measure like it" - and the
clamps are the safety rail. Nine constants across four modules set that rail, each tuned
against its own complaint, and none of them is reachable by a user. So somebody who wants
more than the default gets nothing: the only control on the page is `match_strength`, and
Experiment 2 measured what that is worth.

**It is worth almost nothing, and that is the reason this module exists.** Sweeping
`match_strength` across its entire range, 0.4 to 1.0, moves the mean spectral distance to
the reference by **0.56 dB** - under half the 1.2 dB this codebase already calls a
meaningful gap - because it scales a curve that has *already been clamped*, and it is
clipped at 1.0 so the top of the slider is not "more". Doubling the clamps behind it buys
**1.07 dB** more, and removing them **2.15 dB**. Everything the strength dial can reach,
the clamps were already holding back by more.

A budget wired to `match_strength` would therefore ship a control that cannot do anything.
That is the obvious way to build this wrong and the card says so in bold.

## What scales, and what deliberately does not

**Ceilings scale. Fractions do not.** `_nudge(gap, limit)` is `clip(gap * share, -limit,
+limit)`, so raising the limit lets a *large* difference move further while leaving a
small one exactly where it was - the fraction still binds there. That is the right shape
for this control: a wider budget should mean "I can see these two records are far apart,
let it move", not "copy the reference". Scaling the share instead would turn a nudge into
a match at the top notch, which is the one thing the product's governing idea forbids:

    "a nudge in a direction of getting closer to the songs i idolized... not a carbon copy."

So `NUDGE_SHARE` and `suggest.CLOSE_FRACTION` are **not** scaled, even though the card
names the second of them. Raising the rail is not the same as changing the ambition, and
the measured headroom is all in the rail anyway.

**The deep-bass guard does not scale either.** `max_low_cut_db` is 1.0 dB below
`low_guard_hz`, and it is 1.0 rather than 2.0 because a master came back with "no bass":
the guard had been protecting the sub while leaving 90-180 Hz exposed, the correction
piled up just above the corner and dug a 5 dB notch at 105 Hz - through the kick and bass
fundamentals, and exactly the band a car stereo reproduces. A budget that scaled it would
re-open a fixed complaint and call it a feature. Anybody who wants less bass has a bass
control that reaches much further than this ever will.

**`LIKELY_ARRANGEMENT_DB` does not scale.** A gap past it is flagged as probably a
difference of arrangement rather than of mixing, at every setting. Widening the budget
means "I accept a bigger move", not "stop telling me when the two records are different
songs".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.mastering.dsp import MatchSettings


@dataclass(frozen=True, slots=True)
class Budget:
    """One notch: a name, a scale on the ceilings, and what it actually permits."""

    name: str
    label: str
    #: Multiplier on every ceiling that is allowed to move. 1.0 is today's behaviour.
    scale: float
    #: One sentence a user reads before choosing it. Says what it permits in decibels,
    #: because "more" is not a unit and this control's whole problem is that the one it
    #: replaces felt like it did something.
    summary: str


#: Two notches, and there is no third because a third was built, measured, and removed.
#:
#: Rendered end to end on the Experiment 2 pair, against an unmastered distance of
#: 5.73 dB: **nudge 4.14 dB** (27.7% closed), **further 3.63** (36.6%), and a ×3 notch
#: **3.57** (37.6%). The third is worth 0.06 dB over the second, which is nothing, and
#: the curve says why. At ×2 the correction sits exactly on the tilt cap - 12.00 dB
#: against a cap of 12. At ×3 it sits at 13.25 against a cap of 18, so the cap has
#: stopped being what holds it back. **The deep-bass guard is.** Lifting that guard from
#: 1 dB to 6 takes the low-end cut from -4.96 to -6.00 dB, which is the move that
#: produced "super hollow with no bass" in the first place.
#:
#: A notch past "further" is therefore a control that measurably does nothing unless it
#: also re-opens a fixed complaint - and shipping a control that does nothing is the
#: exact failure this card was written to prevent. It stops at two.
#:
#: Note what the 0.51 dB figure is and is not. It is the **whole-mix** match, which is
#: all a render measures when nobody has taken a suggestion. The per-instrument ceilings
#: double too, so a large difference on one instrument can move 6 dB instead of 3 and
#: 5 dB of tone instead of 2.5 - well past the 1.2 dB threshold, but only for somebody
#: who presses Apply.
BUDGETS: tuple[Budget, ...] = (
    Budget(
        name="nudge",
        label="Nudge",
        scale=1.0,
        summary=(
            "Moves each instrument up to 3 dB, each tone band up to 2.5 dB, and tilts "
            "the whole master by at most 6 dB end to end. The default, and what every "
            "number in this app was tuned against."
        ),
    ),
    Budget(
        name="further",
        label="Further",
        scale=2.0,
        summary=(
            "Doubles every ceiling: 6 dB an instrument, 5 dB a band, 12 dB of tilt. "
            "Measured at 0.51 dB more closure on the whole mix - real but under this "
            "app's own 1.2 dB threshold for a difference worth mentioning, so most of "
            "what it buys is in the per-instrument suggestions, where a large gap can "
            "now move twice as far. Small differences do not move at all either way, and "
            "nothing becomes a copy. There is no setting past this one: a wider notch "
            "was built and measured at 0.06 dB, because the deep-bass guard takes over "
            "and it is not going to be moved."
        ),
    ),
)

DEFAULT = "nudge"

_BY_NAME = {budget.name: budget for budget in BUDGETS}


def get(name: str | None) -> Budget:
    """The named notch, or the default. An unknown name is the default rather than an
    error: a budget arriving from an older client should cost nothing."""
    return _BY_NAME.get(name or DEFAULT, _BY_NAME[DEFAULT])


@dataclass(frozen=True, slots=True)
class Limits:
    """The per-instrument ceilings, scaled. Mirrors the constants in `instrument`.

    Passed rather than read from the module, so that one comparison can run at one budget
    without a global changing underneath another. The defaults are `instrument`'s own
    values, so `Limits()` is today's behaviour and nothing has to pass one.
    """

    max_level_db: float = 3.0
    max_band_db: float = 2.5
    tone_budget_db: float = 5.0
    width_limits: tuple[float, float] = (0.8, 1.35)

    @property
    def describes_level(self) -> str:
        return f"{self.max_level_db:.1f} dB"


def limits_for(budget: Budget | str | None) -> Limits:
    """The per-instrument ceilings at this budget.

    Width is scaled around 1.0 rather than multiplied, because width is a ratio and not a
    quantity of decibels: doubling the *limits* (0.8, 1.35) would give (1.6, 2.7), a floor
    of 1.6 that forbids ever narrowing anything. Scaling the distance from unity gives
    (0.6, 1.7), which is what "twice as much width change" means.
    """
    chosen = budget if isinstance(budget, Budget) else get(budget)
    scale = chosen.scale
    low, high = Limits().width_limits
    return Limits(
        max_level_db=round(Limits().max_level_db * scale, 2),
        max_band_db=round(Limits().max_band_db * scale, 2),
        tone_budget_db=round(Limits().tone_budget_db * scale, 2),
        width_limits=(
            round(max(1.0 - (1.0 - low) * scale, 0.1), 3),
            round(1.0 + (high - 1.0) * scale, 3),
        ),
    )


def match_settings_for(
    budget: Budget | str | None, base: MatchSettings | None = None
) -> MatchSettings:
    """The whole-mix match's clamps at this budget.

    These are the ones Experiment 2 actually varied, and therefore the only ones with a
    measured effect behind them. `max_low_cut_db` and `low_guard_hz` are passed through
    untouched - see the module docstring for the complaint that fixed them there.
    """
    chosen = budget if isinstance(budget, Budget) else get(budget)
    settings = base or MatchSettings()
    if chosen.scale == 1.0:
        return settings
    return replace(
        settings,
        max_boost_db=round(settings.max_boost_db * chosen.scale, 2),
        max_cut_db=round(settings.max_cut_db * chosen.scale, 2),
        max_tilt_db=round(settings.max_tilt_db * chosen.scale, 2),
    )


def stem_gain_limit_for(budget: Budget | str | None, base: float = 9.0) -> float:
    """`stem_match.MAX_STEM_GAIN_DB` at this budget.

    Not scaled as hard as the rest. Nine decibels on one stem against four on another is
    already a thirteen-decibel swing between two instruments, and this is the clamp that
    produced the "+9 dB of nothing" bug X0R-1127 was filed for. The square root of the
    scale widens it without letting the top notch reach twenty-seven.
    """
    chosen = budget if isinstance(budget, Budget) else get(budget)
    return round(base * chosen.scale**0.5, 2)


def as_json() -> list[dict]:
    """The notches, for the page to build a control out of."""
    return [
        {
            "name": b.name,
            "label": b.label,
            "scale": b.scale,
            "summary": b.summary,
            "default": b.name == DEFAULT,
        }
        for b in BUDGETS
    ]
