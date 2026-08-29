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
    """OUTPUT, line by line, against the file each block names in an HTML comment."""
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

NEGATIONS = ("not ", "no ", "never ", "nothing ", "cannot ", "does not", "without ")


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", " ".join(text.split()))]


@pytest.mark.parametrize("phrase", CLAIMS_TO_AVOID)
def test_the_page_never_claims_what_it_cannot_support(phrase: str) -> None:
    """THE CHECK IS ON THE CLAIM, NOT THE WORD, and the first version was on the word.

    It failed on this repository's own disclaimers: "It is not Airflow in production", "does not
    allocate capital, hold a track record, or claim any strategy makes money". A ban that fires
    on the sentence saying no is a ban that pushes the disclaimer off the page, which is the
    opposite of what it is for.

    So every sentence containing one of these has to contain a negation as well.
    """
    for sentence in sentences(own_prose()):
        if phrase in sentence.lower():
            assert any(negation in sentence.lower() for negation in NEGATIONS), (
                f"this sentence claims {phrase!r} rather than denying it: {sentence!r}"
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
