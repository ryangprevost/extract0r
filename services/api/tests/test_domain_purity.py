"""`app/domain/` depends on nothing but the standard library. X0R-102.

That card has said so since the first week and **nothing enforced it**, which is how it came
to be broken: X0R-1319's tempo map was written into `app/domain/` importing numpy, the whole
suite stayed green, and the only reason it was caught is that somebody happened to re-read
X0R-102 afterwards. A documented invariant with no test is a comment.

Why it is worth a test rather than a note. The card's reason is *"so that the interesting
logic is testable without a 2 GB ML install"*, and the slide is gradual: numpy is a small
wheel and already a base dependency, so importing it breaks nothing today. It breaks the rule
that makes the next import arguable, and the one after that is scipy, and then somebody needs
librosa for one function and the domain is no longer testable on a bare checkout. The line is
worth holding exactly because each individual crossing looks harmless.

The tempo map now lives in `app/services/analysis/`, which is where it belonged regardless: it
fits a model to measured onsets, and that is analysis, not a domain type.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

DOMAIN = Path(__file__).resolve().parents[1] / "app" / "domain"

#: Packages in `requirements.txt` rather than `requirements-ml.txt`. Listed so a failure can
#: say *which* kind of dependency crept in - a base one is a rule violation, an ML one would
#: also break the fast test job outright.
BASE_PACKAGES = {
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic_settings",
    "multipart",
    "numpy",
    "soundfile",
    "soxr",
    "av",
    "scipy",
    "lameenc",
    "pyloudnorm",
    "httpx",
}


def modules() -> list[Path]:
    return sorted(p for p in DOMAIN.rglob("*.py") if p.name != "__init__.py")


def imported_roots(path: Path) -> set[str]:
    """Every top-level package name the file imports, including inside functions.

    The AST rather than importing the module: an import hidden in a function body is still a
    dependency, it just fails later and somewhere less obvious.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_there_is_something_to_check():
    """A glob that silently matches nothing would make every test below vacuous."""
    assert len(modules()) > 3


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_a_domain_module_imports_only_the_standard_library(path: Path):
    outside = {
        root
        for root in imported_roots(path)
        if root != "app" and root not in sys.stdlib_module_names
    }
    assert not outside, (
        f"{path.name} imports {sorted(outside)}. X0R-102: app/domain/ depends on nothing but "
        f"the standard library, so the interesting logic stays testable on a bare checkout. "
        f"{'Base dependency - still a rule violation. ' if outside & BASE_PACKAGES else ''}"
        f"Analysis that needs numpy belongs in app/services/analysis/."
    )


def test_the_check_would_actually_catch_one():
    """The test above passes trivially if `imported_roots` returns nothing useful, which is
    the failure mode of every lint-by-AST check ever written."""
    assert imported_roots(DOMAIN / "timing.py")
    assert "numpy" in imported_roots(
        Path(__file__).resolve().parents[1] / "app" / "services" / "analysis" / "tempo_map.py"
    )
