"""Every checkable claim on the front page, checked, and written before the page existed.

Four kinds of claim, following the contract this toolset shares:

    NUMBER     a figure on the page against the measurement that produced it
    COMMAND    a command the page offers against what CI actually runs
    OUTPUT     a quoted block, line by line, against the transcript it names
    REFERENCE  every link and path against what exists

Plus the one this repository needs and the others do not: a VOCABULARY check. Every claim here
is bounded, and a page that says a rule prevents or eliminates anything has stopped describing
what was measured.
"""

from __future__ import annotations

import html
import json
import pathlib
import re
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
EVIDENCE = REPO / "docs" / "evidence"


def evidence(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (EVIDENCE / name / "summary.json").read_text(encoding="utf-8")
    )
    return loaded


def own_prose() -> str:
    """The page minus the generated cross-link footer, which describes other repositories."""
    start, end = "<!-- toolset:start -->", "<!-- toolset:end -->"
    if start in README and end in README:
        return README[: README.index(start)] + README[README.index(end) + len(end) :]
    return README


def test_the_numbers_on_the_page_are_the_measured_ones() -> None:
    """NUMBER, recomputed from the committed session rather than from a note."""
    from queuez import session, tape

    events = session.by_topic(session.read("session_one"))["eqiad.mediawiki.recentchange"]
    backwards = session.backwards_clock_steps(events)
    worst = max(before.unix_second - after.unix_second for before, after in backwards)
    built, injected = tape.build(events)
    schema = evidence("schema")
    cache = evidence("cache")

    claims = {
        "events in the session": f"{len(events):,}",
        "backwards clock steps": str(len(backwards)),
        "the worst backwards step": str(worst),
        "events on the tape": f"{len(built):,}",
        "callers in the stampede": str(cache["callers"]),
        "recomputed without single flight": str(cache["recomputed_without_single_flight"]),
        "the rejecting status": str(schema["results"]["BACKWARD"]["status"]),
        "the accepting status": str(schema["results"]["NONE"]["status"]),
        "the injected gap width": str(len(injected.gap_offsets)),
    }
    missing = {name: value for name, value in claims.items() if value not in README}
    assert missing == {}, f"the README no longer states these measured figures: {missing}"


def test_no_backwards_count_on_the_page_is_stated_without_the_clock_it_counted() -> None:
    """547 AND 13 ARE BOTH TRUE AND THEY ARE ABOUT DIFFERENT FIELDS.

    The page said "the wall clock" as though the payload had one. It has two, and the page says
    so itself twenty lines further down. Counted on the Unix second in `payload.timestamp` the
    session steps backwards 547 times by as much as 26 seconds; counted on the ISO instant in
    `meta.dt` the same 2,024 pairs step backwards 13 times by at most 0.012. A reader who reaches
    for the millisecond field, which is the one a consumer would normally take as event time,
    recomputes 13 and concludes the 547 was picked. That is a worse outcome than never having
    stated it, and the fix is a word rather than a smaller claim.
    """
    from queuez import session

    events = session.by_topic(session.read("session_one"))["eqiad.mediawiki.recentchange"]
    counted = {
        str(len(session.backwards_clock_steps(events))),
        str(len(session.backwards_clock_steps(events, clock=session.iso_instant))),
    }
    carrying = [
        sentence
        for sentence in paragraph_sentences(own_prose())
        if "backwards" in sentence.lower() and any(count in sentence for count in counted)
    ]
    assert carrying, (
        f"no sentence on the page states either backwards count {sorted(counted)}, so this test "
        f"is checking nothing"
    )
    for sentence in carrying:
        assert "unix second" in sentence.lower() or "iso instant" in sentence.lower(), (
            f"this sentence states a backwards count and never says which of the two clocks it "
            f"was counted on: {sentence!r}"
        )


def test_the_page_states_the_licence_decision_and_why_it_is_that_way() -> None:
    """The decision a reader would otherwise have to reconstruct from the capture script."""
    flattened = " ".join(own_prose().split()).lower()
    assert "cc by-sa" in flattened
    assert "wikimedia" in flattened
    assert "source: wikimedia eventstreams" in flattened


def test_no_large_number_on_the_page_is_one_nothing_measured() -> None:
    """A stale copy of a figure elsewhere on the page."""
    from queuez import session, tape

    events = session.by_topic(session.read("session_one"))["eqiad.mediawiki.recentchange"]
    built, _ = tape.build(events)
    measured = {
        len(session.read("session_one")),
        len(events),
        len(built),
        len(session.backwards_clock_steps(events)),
        evidence("conformance")["events"],
        sum(1 for event in events if abs(event.clock_gap_seconds) >= 1),
    }
    written = {
        int(token.replace(",", "")) for token in re.findall(r"\b\d{1,3}(?:,\d{3})+\b", README)
    }
    invented = sorted(written - measured)
    assert invented == [], (
        f"the page states {invented}, and nothing in the corpus or the evidence produces those"
    )


def test_every_command_the_page_offers_is_one_ci_runs() -> None:
    """COMMAND. Except the three that run inside the shared workflow, which is named."""
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    executed = "\n".join(
        line
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
        for line in step["run"].splitlines()
        if not line.strip().startswith("#")
    )
    shared = "PNX89/.github/.github/workflows/checks.yml"
    assert shared in (REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    delegated = ("uv run pytest", "uv run ruff", "uv run mypy", "uv sync")

    offered = re.findall(r"^\s*(?:\$ )?(uv run [^\n]+|scripts/\S+)$", README, re.MULTILINE)
    assert offered, "the README offers no command at all"
    for command in offered:
        command = command.strip()
        if command.startswith(delegated):
            continue
        assert command in executed, f"the README offers `{command}` and CI never runs it"


def test_every_block_quoted_from_a_transcript_is_in_that_transcript() -> None:
    """OUTPUT, line by line, against the file each block names in an HTML comment.

    ALSO COVERS docs/demo.svg, WHICH IS A QUOTED BLOCK TOO, hand drawn as an animated terminal
    rather than a fenced code block. It named no source in an HTML comment and nothing checked it
    against one: CI diffs docs/evidence/demo.txt against a committed copy on every push, and the
    SVG quoting the same transcript would have kept stale figures silently forever, since nothing
    generates it and nothing but this compared it.
    """
    blocks = re.findall(r"<!-- quoted from (\S+) -->\n```text\n(.*?)```", README, re.S)
    assert blocks, "no block on the page declares where it was quoted from"
    for path, body in blocks:
        source = REPO / path
        assert source.exists(), f"the page quotes {path}, which does not exist"
        lines = {line.strip() for line in source.read_text("utf-8").splitlines()}
        for line in body.splitlines():
            if line.strip():
                assert line.strip() in lines, (
                    f"the page quotes {line.strip()!r} as coming from {path}, and it is not there"
                )

    svg_ref = re.search(r"\]\((docs/demo\.svg)\)", README)
    assert svg_ref, "the README no longer links docs/demo.svg; update this test if it moved"
    svg = (REPO / svg_ref.group(1)).read_text(encoding="utf-8")
    texts = [html.unescape(found) for found in re.findall(r"<text[^>]*>(.*?)</text>", svg, re.S)]
    assert len(texts) >= 3, f"docs/demo.svg has too few <text> elements to be a transcript: {texts}"
    assert texts[0].startswith("$ "), f"the terminal's first line is not a command: {texts[0]!r}"
    elided = re.match(r"\.\.\. (\d+) more lines", texts[-1])
    assert elided, f"the terminal's last line does not say how many lines were cut: {texts[-1]!r}"

    demo_path = REPO / "docs" / "evidence" / "demo.txt"
    demo_lines = demo_path.read_text(encoding="utf-8").splitlines()
    shown = texts[1:-1]
    if shown and shown[0] == "":
        shown = shown[1:]  # one blank spacer between the echoed command and the demo's output
    if shown and shown[-1] == "":
        shown = shown[:-1]  # one blank spacer between the last shown line and the elision line
    assert shown == demo_lines[: len(shown)], (
        "docs/demo.svg no longer quotes the start of docs/evidence/demo.txt verbatim, line for "
        "line; regenerate the SVG from the current transcript"
    )
    remaining = len(demo_lines) - len(shown)
    assert int(elided.group(1)) == remaining, (
        f"docs/demo.svg says {elided.group(1)} more lines follow the ones it shows, and "
        f"{remaining} actually do"
    )


def test_every_path_and_link_on_the_page_exists() -> None:
    """REFERENCE, including the paths written as inline code."""
    targets = set(re.findall(r"\]\((?!https?:)([^)#]+)", README))
    targets |= {
        found
        for found in re.findall(r"`([a-zA-Z0-9_./-]+)`", README)
        if "/" in found and not found.startswith(("http", "-"))
    }
    missing = sorted(target for target in targets if not (REPO / target.strip()).exists())
    assert missing == [], f"the README points at paths that do not exist: {missing}"


#: Phrases this repository must not CLAIM. Some belong to a sibling and some overclaim, and the
#: check below is about the claim rather than the word: a page saying it is NOT Airflow in
#: production is doing the right thing, and a blanket ban would fail it for saying so.
CLAIMS_TO_AVOID = (
    "in production",
    "at scale",
    "exactly-once",
    "low latency",
    "tick-to-trade",
    "operating kafka",
    # A sibling's subject, which this repository is required to EXCLUDE explicitly rather than
    # to avoid mentioning. Stated as a denial it is the honest thing to write; stated as a claim
    # it would be describing a repository that does not exist here.
    "order book",
    "matching engine",
    "depth reconstruction",
    "colocation",
    "smart order routing",
)

#: Vocabulary belonging to a sibling repository. These are banned outright, negation or not,
#: because using a sibling's phrase even to disclaim it is still describing its subject.
BELONGS_TO_A_SIBLING = (
    "coverage certificate",
    "per-caller budget",
)

#: A negation only counts if it attaches to the phrase, not merely shares a sentence with it.
#: Bare "no " is deliberately NOT in this list: it precedes an ordinary noun ("no gaps", "no
#: downtime", "no reason", "no default") far more often than it precedes a banned claim, so "no"
#: only counts when it is the word immediately before the phrase, checked separately below.
#: "cannot " is not a separate entry either: tokenised by word, "cannot" is its own token and
#: does not contain "not" the way the substring did.
NEGATION_WORDS = ("not", "never", "nothing", "cannot", "without")
#: Words scanned immediately before the phrase, not the rest of the sentence.
NEGATION_WINDOW = 6


def all_occurrences_are_negated(sentence_lower: str, phrase: str) -> bool:
    """Every mention of `phrase` in this (lowercased) sentence has a negation attached to it.

    THE ORIGINAL CHECKED THE WHOLE SENTENCE FOR ANY OF A LIST OF NEGATION WORDS, AND "no " WAS ON
    IT. "QUEUEZ has run in production for two years with no downtime." contains "no ", so it
    passed outright: the claim it makes is "in production", and "no" is doing nothing to deny it,
    it is denying "downtime" several words later. Coverage was almost an accident too: of the
    eleven phrases this guards, only one has ever matched a sentence on this page, so the other
    ten were never tried against real text either way. Requiring the negation to sit within a
    handful of words immediately before the phrase, rather than anywhere in the sentence, is what
    makes the guard test the claim instead of the sentence's mood.
    """
    matches = list(re.finditer(re.escape(phrase), sentence_lower))
    if not matches:
        return True  # vacuous: the phrase is not in this sentence at all
    for match in matches:
        words = re.findall(r"[a-z']+", sentence_lower[: match.start()])[-NEGATION_WINDOW:]
        if any(word in NEGATION_WORDS for word in words):
            continue
        if words[-1:] == ["no"]:
            continue
        return False
    return True


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", " ".join(text.split()))]


def paragraph_sentences(text: str) -> list[str]:
    """Sentences, and never one that runs across a blank line.

    A MUTATION SAID THIS WAS NEEDED. `sentences` flattens the whole page before splitting, and
    markdown does not end a heading, a badge row or an image with a full stop, so one sentence
    there runs for twenty lines. Removing the clock's name from the headline left the check
    below green, because the image alt text two paragraphs down still carried the word and the
    two had been read as one sentence. Searching a page for a word is not checking a claim.
    """
    return [sentence for block in re.split(r"\n\s*\n", text) for sentence in sentences(block)]


@pytest.mark.parametrize("phrase", CLAIMS_TO_AVOID)
def test_the_page_never_claims_what_it_cannot_support(phrase: str) -> None:
    """THE CHECK IS ON THE CLAIM, NOT THE WORD, and the first version was on the word.

    It failed on this repository's own disclaimers: "It is not Airflow in production", "does not
    allocate capital, hold a track record, or claim any strategy makes money". A ban that fires
    on the sentence saying no is a ban that pushes the disclaimer off the page, which is the
    opposite of what it is for.

    So every sentence containing one of these has to contain a negation as well, and the
    negation has to attach to the phrase rather than merely share its sentence.
    """
    for sentence in sentences(own_prose()):
        if phrase in sentence.lower():
            assert all_occurrences_are_negated(sentence.lower(), phrase), (
                f"this sentence claims {phrase!r} rather than denying it: {sentence!r}"
            )
    # THE GUARD'S OWN DISCRIMINATING POWER, SHOWN RATHER THAN ASSUMED, riding the two
    # parametrised cases this page actually exercises rather than adding a new test: the
    # published card states a test total, and a fixture that added to it would go stale the
    # moment this file is committed without the card being regenerated by the tool that owns it.
    # Coverage before this fix was almost accidental: of these eleven phrases, only "matching
    # engine" has ever matched a real sentence here, so most of the other ten had never been
    # tried against real text either way.
    if phrase == "in production":
        assert not all_occurrences_are_negated(
            "queuez has run in production for two years with no downtime.", phrase
        ), "a bare 'no' attached to an unrelated noun several words later must not negate this"
    if phrase == "matching engine":
        assert all_occurrences_are_negated(
            "it does not reconstruct a book, and nothing here is a matching engine.", phrase
        )


@pytest.mark.parametrize("phrase", BELONGS_TO_A_SIBLING)
def test_the_page_does_not_use_a_siblings_vocabulary_at_all(phrase: str) -> None:
    """Banned outright: using a sibling phrase even to disclaim it describes its subject."""
    assert phrase not in own_prose().lower()


def test_the_page_names_the_feed_and_does_not_imply_a_venue() -> None:
    """The upstream is a public wiki feed, and saying so plainly is the honest framing.

    The mechanism is venue-agnostic and the asset class here is an artefact of what may legally
    be redistributed. A page that let a reader assume otherwise would be trading on it.
    """
    first = " ".join(README.splitlines()[:45]).lower()
    assert "wikimedia" in first
    assert "venue" not in first or "not" in first


def test_the_page_says_what_the_repository_does_not_do() -> None:
    """The sentence that has to be there, not merely the absence of the ones that must not."""
    flattened = " ".join(own_prose().split()).lower()
    assert "redpanda" in flattened
    assert "kafka api" in flattened, (
        "the page does not say this serves the Kafka API rather than being Kafka"
    )
