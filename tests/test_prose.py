"""Two things a reader meets before any code, and neither of them is checkable by a type system.

PROSE WRITTEN TWICE. This repository argues in sentences, in the README, in module docstrings and
in the comments beside the decisions they explain. That works exactly once per sentence. The same
aphorism in four files stops reading as a voice and starts reading as a template, and a reviewer
who notices the repetition reads the rest of the page differently. Three sentences were written
out four, three and two times here before this test existed.

A DOCUMENT NAMED THAT IS NOT THERE. A file pointing at `SOMETHING.md` is making a promise on
behalf of a document, and the reader who follows it finds nothing. That is the same defect the
doc contract already watches for in the README, one layer out: it applies to any file that names
a document, not only to the front page.
"""

from __future__ import annotations

import collections
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Where this repository's own prose lives. An INCLUSION list rather than an exclusion one. The
#: card, the frame, the contributing guide, the templates and tests/test_doc_contract.py are
#: written by a generator outside this repository from a manifest sixteen of them share, so a
#: sentence two of those have in common is not one anybody here typed twice. An exclusion list
#: would quietly admit the next generated file to arrive.
AUTHORED = (
    "README.md",
    "DOCDRIFT.md",
    "pyproject.toml",
    ".github/workflows",
    "decoder/src",
    "examples",
    "scripts",
    "src",
    "tests",
    "tests_broker",
)

#: The one generated file inside those paths. It is excluded from the repetition check and NOT
#: from the check below it: a sentence it shares with a sibling is the manifest's business, and
#: a document it names that is not here is this repository's, because only this repository can
#: put the document there.
GENERATED = ("tests/test_doc_contract.py",)

#: What any file can be read for a document name, which is all of them.
READABLE = (".py", ".md", ".rs", ".yml", ".toml")

#: Comment and list markers, stripped per line so that a sentence repeated between a paragraph
#: and a comment is still recognised as the same sentence.
MARKER = re.compile(r"^\s*(#|//!|//|\*|-{2,}|>)\s?")

#: Below this a match is likelier to be a coincidence than a copy. Eight words is well clear.
LONG_ENOUGH = 8

#: A document named in upper case, which is how every document in this tree is named.
DOCUMENT = re.compile(r"\b([A-Z][A-Z0-9_]*\.md)\b")


def tracked_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO, check=True
    ).stdout.split()
    return [entry for entry in listed if entry.endswith(READABLE)]


def authored_files() -> list[str]:
    return [
        entry for entry in tracked_files() if entry.startswith(AUTHORED) and entry not in GENERATED
    ]


def sentences_in(text: str) -> list[str]:
    """The sentences of a file, whatever syntax they are embedded in."""
    flattened = " ".join(MARKER.sub("", line).strip() for line in text.splitlines())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", " ".join(flattened.split()))]


def written_twice(documents: dict[str, str]) -> dict[str, list[str]]:
    """Sentences appearing in more than one of the given documents, and where."""
    homes: dict[str, set[str]] = collections.defaultdict(set)
    for name, text in documents.items():
        for sentence in sentences_in(text):
            if len(sentence.split()) >= LONG_ENOUGH:
                homes[sentence].add(name)
    return {sentence: sorted(where) for sentence, where in homes.items() if len(where) > 1}


def documents_named(text: str) -> set[str]:
    """Every document this text points at by name."""
    return set(DOCUMENT.findall(text))


def test_no_sentence_in_this_repository_is_written_twice() -> None:
    """ONE HOME PER CLAIM, and four sentences had more than one the first time this ran.

    A claim made once and referred to from the code is stronger than the same sentence in four
    files: the reader who meets it twice stops hearing an argument and starts hearing a
    template. Three of the four were long-standing and the fourth was introduced by the same
    change that added this test, which is a fair account of how easily it happens.

    The rule is about verbatim repetition and not about restating an argument in its own place,
    which is the whole job of a docstring.
    """
    repeated = written_twice(
        {name: (REPO / name).read_text(encoding="utf-8") for name in authored_files()}
    )
    assert repeated == {}, "\n".join(
        f"{sentence!r} is written in {where}" for sentence, where in sorted(repeated.items())
    )


def test_the_duplicate_finder_reports_a_sentence_written_twice() -> None:
    """THE GUARD ABOVE, POINTED AT PROSE THAT REPEATS ITSELF.

    It passes now because nothing repeats, which is also what it would do if it had stopped
    comparing. So it is handed two documents that share a sentence, one of them as a comment,
    because a repetition that crosses from prose into a comment is the shape this repository
    actually produced.
    """
    said_once = "A consumer tested against a healthy feed alone has been tested against nothing."
    shared = written_twice(
        {
            "one.md": f"Something else entirely. {said_once}",
            "two.py": f"# {said_once}\n# And a different sentence after it, long enough to count.",
        }
    )
    assert list(shared) == [said_once], f"the finder reported {list(shared)}"
    assert shared[said_once] == ["one.md", "two.py"]

    # And the floor, which is the half that stops this reporting every "This is why." twice.
    too_short = "Six words is not a copy."
    assert written_twice({"one.md": too_short, "two.py": too_short}) == {}


def test_every_document_this_repository_names_is_in_it() -> None:
    """A NAMED DOCUMENT THAT DOES NOT EXIST, which is a promise made on its behalf.

    `DOCDRIFT.md` was named twice and existed nowhere in the tree, so a reader following the
    reference from the doc contract to the contract itself found nothing. The README's own paths
    are watched by the doc contract; this covers every other file, which is where nobody looks.
    """
    missing: dict[str, list[str]] = {}
    for name in tracked_files():
        for document in sorted(documents_named((REPO / name).read_text(encoding="utf-8"))):
            if not (REPO / document).exists():
                missing.setdefault(document, []).append(name)
    assert missing == {}, f"these documents are named and do not exist: {missing}"


def test_the_document_finder_reads_a_name_out_of_prose() -> None:
    """The guard above, shown finding the name it is looking for."""
    assert documents_named("The contract itself is in DOCDRIFT.md, which explains it.") == {
        "DOCDRIFT.md"
    }
    assert documents_named("nothing here names a document at all") == set()
