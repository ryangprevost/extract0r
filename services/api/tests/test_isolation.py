"""No test writes into a directory a person owns.

This has now been got wrong twice, in the same way, with the same symptom.

`models_dir` was first: it defaulted to the repo's `models/` folder, so whether a route
reported per-drum separation as available depended on whether the developer had downloaded
a 167 MB file, and the tests that found it there would then shell out to demucs. The fix
was one line in the `settings` fixture and a paragraph explaining it.

`profile_dir` was second, and worse. It defaults to the repo's `profiles/` folder, which is
gitignored precisely because the profiles in it belong to whoever is running this - records
they measured, named as they named them. Every test that saved a profile wrote into that
list, and the leak was only noticed because a new test used a name ("My blend") memorable
enough to spot among them. By then the suite had left `test ref`, `with drums` and
`per-drum e2e` sitting in a real person's data.

Flakiness is the lesser problem. Writing into somebody's own files is the reason this guard
is general rather than a third one-line fix: it asserts that **every** directory a `Settings`
can be pointed at resolves inside the test's own temporary folder, so the next setting to be
added is covered before anybody remembers to think about it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


#: Fields that name a directory this application may write to or read a person's data from.
#: Derived from `Settings` rather than listed, so a new one cannot be missed - which is the
#: whole point, both previous failures being a field nobody thought about.
def directory_fields() -> list[str]:
    return [
        name
        for name, field in Settings.model_fields.items()
        if "Path" in str(field.annotation)
    ]


def test_every_directory_setting_is_isolated(settings, tmp_path: Path):
    """The guard. Each one resolves inside the test's own folder, or is unset."""
    stray = []
    for name in directory_fields():
        value = getattr(settings, name, None)
        if value is None:
            continue
        resolved = Path(value).resolve()
        if not resolved.is_relative_to(tmp_path.resolve()):
            stray.append(f"{name} -> {resolved}")

    assert not stray, (
        "these point outside the test's temp folder, so a test could write into a "
        "developer's own files:\n  " + "\n  ".join(stray)
    )


def test_the_guard_knows_about_the_two_that_went_wrong():
    """If either is ever renamed, this file should fail rather than quietly stop
    covering them."""
    found = directory_fields()
    assert "profile_dir" in found
    assert "models_dir" in found
    assert "storage_dir" in found


def test_the_real_defaults_are_outside_a_temp_folder(tmp_path: Path):
    """Which is exactly why the fixture has to override them.

    A guard that passed because the defaults happened to be harmless would be worthless,
    so this pins that they are not: `profile_dir` really does point at a person's folder.
    """
    real = Settings(_env_file=None)
    assert not Path(real.profile_dir).resolve().is_relative_to(tmp_path.resolve())
    assert Path(real.profile_dir).name == "profiles"


@pytest.mark.parametrize("name", ["storage_dir", "models_dir", "profile_dir"])
def test_the_fixture_overrides_each_one_explicitly(settings, tmp_path: Path, name: str):
    """Named individually as well as covered generally, so a failure says which."""
    assert Path(getattr(settings, name)).resolve().is_relative_to(tmp_path.resolve())
