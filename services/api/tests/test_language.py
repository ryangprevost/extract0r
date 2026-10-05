"""The words a user reads are American, and stay that way.

Ryan asked for US spellings. This checks the surfaces a person actually sees - string
literals that reach the screen, and the Studio's markup and script - and it is a test
rather than a one-off pass because what defeats a spelling convention is never the first
sweep, it is the fiftieth new sentence written six weeks later.

**Deliberately not checked: comments and docstrings.** They are not user-visible, this
codebase's docstrings are unusually long, and rewriting them would be several hundred
lines of churn in which a real change could not be found. The convention is "what the
user reads", not "what the repository contains", and that boundary is what lets this
test be precise about where it looks.

**Deliberately not checked: identifiers.** A line-based first version over-reported by
about seventy per cent, flagging `const colour`, `$("metre-input")` and - worst -
`centre_bass_hz`, which is an API field name shared with the Python schema. Renaming
that would be a breaking change for a user-visible benefit of exactly zero.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
STUDIO = API.parents[1] / "apps" / "studio" / "wwwroot"

#: British spelling -> the American one. Only forms that occur or plausibly will: a
#: dictionary of every difference in the language would be unreadable and mostly dead.
BRITISH = {
    "colour": "color", "colours": "colors", "coloured": "colored",
    "behaviour": "behavior", "behaviours": "behaviors",
    "centre": "center", "centres": "centers", "centred": "centered",
    "centring": "centering",
    "normalise": "normalize", "normalised": "normalized",
    "normalising": "normalizing", "normalisation": "normalization",
    "analyse": "analyze", "analysed": "analyzed", "analyses": "analyzes",
    "analysing": "analyzing",
    "organise": "organize", "organised": "organized",
    "recognise": "recognize", "recognised": "recognized",
    "metre": "meter", "metres": "meters",
    "defence": "defense", "practise": "practice",
    "modelling": "modeling", "labelled": "labeled", "labelling": "labeling",
    "cancelled": "canceled", "travelled": "traveled",
    "grey": "gray", "favourite": "favorite",
    "neighbour": "neighbor", "neighbouring": "neighboring",
    "apologise": "apologize",
    "summarise": "summarize", "summarised": "summarized", "summarises": "summarizes",
    "emphasise": "emphasize", "emphasised": "emphasized",
    "minimise": "minimize", "maximise": "maximize",
    "optimise": "optimize", "optimised": "optimized",
    "visualise": "visualize", "utilise": "utilize",
    "prioritise": "prioritize", "specialise": "specialize",
    "realise": "realize", "realised": "realized",
    "judgement": "judgment", "judgements": "judgments",
    "ageing": "aging", "catalogue": "catalog",
    "flavour": "flavor", "honour": "honor", "humour": "humor",
    "licence": "license", "offence": "offense", "pretence": "pretense",
    "manoeuvre": "maneuver", "fulfil": "fulfill", "enrol": "enroll",
    "skilful": "skillful", "marvellous": "marvelous",
    "sceptical": "skeptical", "programme": "program", "programmes": "programs",
}

_WORD = re.compile(r"[A-Za-z]+")

#: Prose, rather than a key, a path or a CSS value. A spelling convention is about
#: sentences, and this is what keeps `"centre-bass"` out of the results.
MIN_PROSE_WORDS = 3


def _british_in(text: str) -> list[str]:
    return sorted({w.lower() for w in _WORD.findall(text) if w.lower() in BRITISH})


# --- the API ------------------------------------------------------------------------


def _prose_literals(source: str, path: Path) -> list[tuple[int, str]]:
    """Every string literal in a Python file that is not a docstring.

    Parsed rather than grepped, so a British word in a comment or a docstring - which
    this convention deliberately does not cover - cannot cause a false failure, and a
    word inside an f-string's literal halves cannot hide from it. Most user-facing prose
    here is an f-string, so a checker that missed those would pass on nearly everything
    that matters.
    """
    tree = ast.parse(source, filename=str(path))

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))

    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and len(node.value.split()) >= MIN_PROSE_WORDS
    ]


def _python_offenders() -> list[str]:
    found = []
    for path in sorted((API / "app").rglob("*.py")):
        for line, text in _prose_literals(path.read_text(encoding="utf-8"), path):
            words = _british_in(text)
            if words:
                found.append(f"{path.relative_to(API)}:{line} {', '.join(words)}")
    return found


# --- the Studio ---------------------------------------------------------------------

_JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
#: Single, double and template literals. Escapes are not interpreted, which would only
#: matter for a word split across one, and no such word exists.
_JS_STRING = re.compile(
    r'"(?:[^"\\\n]|\\.)*"' r"|'(?:[^'\\\n]|\\.)*'" r"|`(?:[^`\\]|\\.)*`", re.S
)
#: Attributes a person reads. `id`, `class` and `data-*` are not among them.
_HTML_VISIBLE_ATTR = re.compile(r'(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)"', re.I)
_HTML_TAG = re.compile(r"<[^>]+>", re.S)


def _studio_offenders(root: Path | None = None) -> list[str]:
    # `root` is for this checker's own tests. Importing the module by name to
    # monkeypatch a global works under one pytest invocation and not another,
    # which is a worse dependency than one optional argument.
    root = root or STUDIO
    found: list[str] = []
    for path in sorted(root.glob("*.js")) + sorted(root.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        is_html = path.suffix == ".html"
        pattern = _HTML_COMMENT if is_html else _JS_COMMENT
        # Each comment becomes its own newlines rather than a space. Collapsing a block
        # comment to one character shifts every line number after it, and the first run
        # of this checker pointed at lines holding `} catch {` and a blank line.
        stripped = pattern.sub(lambda m: "\n" * m.group().count("\n"), text)

        for number, line in enumerate(stripped.split("\n"), 1):
            # Each literal judged on its own, not the whole line joined together.
            # Joining made a line of DOM ids - "sparkle", "centre-bass", "subsonic" -
            # look like a nine-word sentence, and `$("centre-bass-out")` beside a
            # template literal look like another. Both were false positives against
            # identifiers, which is exactly what this checker must never flag.
            if is_html:
                pieces = _HTML_VISIBLE_ATTR.findall(line) + [_HTML_TAG.sub(" ", line)]
            else:
                pieces = [m.group()[1:-1] for m in _JS_STRING.finditer(line)]
            prose = [p for p in pieces if len(p.split()) >= MIN_PROSE_WORDS]
            if not prose:
                continue
            words = _british_in(" ".join(prose))
            if words:
                found.append(f"{path.name}:{number} {', '.join(words)}")
    return found


# --- the convention -------------------------------------------------------------------


def test_nothing_the_api_says_is_spelled_the_british_way():
    offenders = _python_offenders()
    assert not offenders, "British spellings in text a user reads:\n" + "\n".join(offenders)


def test_nothing_the_studio_shows_is_spelled_the_british_way():
    offenders = _studio_offenders()
    assert not offenders, "British spellings in the Studio:\n" + "\n".join(offenders)


# --- the checker itself, because one that cannot fail is not a check --------------------


def test_it_finds_a_british_word_in_a_sentence(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text('x = "the vocal sits in the centre of the mix"\n', encoding="utf-8")
    found = _prose_literals(path.read_text(encoding="utf-8"), path)
    assert _british_in(found[0][1]) == ["centre"]


def test_it_ignores_a_docstring(tmp_path):
    """The boundary the convention rests on."""
    path = tmp_path / "sample.py"
    path.write_text('"""About the centre of the mix."""\nx = 1\n', encoding="utf-8")
    assert _prose_literals(path.read_text(encoding="utf-8"), path) == []


def test_it_ignores_a_comment(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text("# the centre of the mix\nx = 1\n", encoding="utf-8")
    assert _prose_literals(path.read_text(encoding="utf-8"), path) == []


def test_it_reads_the_literal_halves_of_an_f_string(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text('x = f"the {name} sits in the centre of it"\n', encoding="utf-8")
    texts = [t for _, t in _prose_literals(path.read_text(encoding="utf-8"), path)]
    assert any("centre" in t for t in texts)


def test_a_short_literal_is_not_prose(tmp_path):
    """`"centre-bass"` is a DOM id and an API field, not a sentence. The three-word
    filter is the only thing between this convention and a breaking rename."""
    path = tmp_path / "sample.py"
    path.write_text('x = "centre-bass"\n', encoding="utf-8")
    assert _prose_literals(path.read_text(encoding="utf-8"), path) == []


def test_an_identifier_is_not_checked(tmp_path):
    """A JavaScript variable called `colour` is not something a user reads."""
    studio = tmp_path / "wwwroot"
    studio.mkdir()
    (studio / "x.js").write_text(
        'const colour = "#fff";\nconst grey = 1;\n', encoding="utf-8"
    )
    assert _studio_offenders(studio) == []


def test_a_sentence_in_the_studio_is_checked(tmp_path):
    studio = tmp_path / "wwwroot"
    studio.mkdir()
    (studio / "x.js").write_text(
        'say("the bass stays centred so it holds");\n', encoding="utf-8"
    )
    assert "centred" in _studio_offenders(studio)[0]


def test_a_readable_html_attribute_is_checked(tmp_path):
    studio = tmp_path / "wwwroot"
    studio.mkdir()
    (studio / "x.html").write_text(
        '<button id="centre-bass" title="keeps the bass centred in the mix">x</button>\n',
        encoding="utf-8",
    )
    offenders = _studio_offenders(studio)
    assert offenders and "centred" in offenders[0]


def test_a_line_of_dom_ids_is_not_a_sentence(tmp_path):
    """Joining every literal on a line made `"sparkle", "centre-bass", "subsonic"` look
    like a nine-word sentence. Each literal is judged on its own."""
    studio = tmp_path / "wwwroot"
    studio.mkdir()
    (studio / "x.js").write_text(
        'const ids = ["sparkle", "centre-bass", "subsonic", "ambience"];\n',
        encoding="utf-8",
    )
    assert _studio_offenders(studio) == []


@pytest.mark.parametrize("british,american", list(BRITISH.items())[:6])
def test_every_mapping_actually_differs(british, american):
    assert british != american
