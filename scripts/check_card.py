"""Compare the published card against the capture and the measurements it states.

    python3 scripts/check_card.py

WHAT THIS IS FOR, AND IT IS THE HIGHEST COST THING IN THE REPOSITORY TO GET WRONG. site/index.html
is the public URL. An interviewer reaches it before the code, and its own note tells them that
"a test fails when it stops matching a live run, so this page cannot quietly drift from the code
it describes". The check standing behind that sentence compared ONE line, the first line of the
captured transcript, and the publication gate compared the same one. The other twenty-nine lines
of the terminal block, the claim paragraph carrying 547 and 26 seconds, and the test count in the
facts strip were compared against nothing. A card claiming three backwards steps out of eleven,
and four thousand tests, published with a green build. The sentence making the guarantee was
itself the thing that was false.

STDLIB ONLY, AND IT PUTS `src` ON THE PATH RATHER THAN IMPORTING AN INSTALLED PACKAGE, so the
publication workflow can run it with the python3 already on the runner. That workflow builds
nothing on purpose and this does not change it.

WHAT IS COMPARED, AND WHY NOT MORE THAN THIS. The captured block is compared whole, because it is
a transcript and a transcript either matches or does not. The facts strip is compared cell by
cell against the file that generated it. The claim paragraph is compared FIGURE BY FIGURE in the
sentence that carries the claim, rather than by looking for a number anywhere on the page: a page
this long contains every short digit string somewhere, and the card is generated from a shared
manifest that is entitled to rephrase the sentence around the number.
"""

from __future__ import annotations

import html as html_module
import json
import pathlib
import re
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
CARD = ROOT / "site" / "index.html"
EVIDENCE = ROOT / "docs" / "evidence"
TOPIC = "eqiad.mediawiki.recentchange"

#: The label in the facts strip, and the key in facts.json it was generated from.
FACT_CELLS = {"tests": "tests", "python": "python", "release": "release"}

#: A number in prose, with thousands separators allowed and decimals excluded. `0.012` and the
#: `3.13` of a version range each yield nothing rather than a pair of integers, because a decimal
#: is not a figure this compares. The trailing dot of a sentence is not a decimal point, which
#: the first draft of this got wrong: it read `2,024.` as the single digit 2.
FIGURE = re.compile(r"(?<![\d.])\d[\d,]*(?!\.?\d)")


def text_of(fragment: str) -> str:
    """Tags out, entities back to characters. The card is generated and its markup is flat."""
    return html_module.unescape(re.sub(r"<[^>]+>", "", fragment))


def captured_block(card: str) -> str | None:
    """The terminal panel, which is the demo's stdout verbatim."""
    found = re.search(r"<pre[^>]*>(.*?)</pre>", card, re.S)
    return None if found is None else text_of(found.group(1))


def facts_shown(card: str) -> dict[str, str]:
    """The facts strip as label to value, so each cell is compared against its own fact."""
    return {
        text_of(label).strip().lower(): text_of(value).strip()
        for label, value in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", card, re.S)
    }


def claim_prose(card: str) -> list[str]:
    """The sentences of the card's own argument: the claim paragraph and the unfurl description.

    Deliberately NOT the whole page. The captured block is prose too and it is compared whole
    somewhere better, and a check that read the whole document would be reading the terminal
    output twice under a weaker rule.
    """
    fragments = [
        found.group(1)
        for pattern in (
            r'<p class="claim">(.*?)</p>',
            r'<meta property="og:description" content="([^"]*)"',
        )
        if (found := re.search(pattern, card, re.S)) is not None
    ]
    prose = " ".join(text_of(fragment) for fragment in fragments)
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", " ".join(prose.split()))]


def normalised(block: str) -> list[str]:
    """Trailing whitespace and the blank lines at either end are not content."""
    return [line.rstrip() for line in block.strip("\n").splitlines()]


def measured_figures() -> set[int]:
    """The vocabulary a sentence about the backwards clock is entitled to use.

    Nothing else belongs in that sentence, so anything else in it is a figure the repository
    does not produce.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from queuez import session

    events = session.by_topic(session.read("session_one"))[TOPIC]
    backwards = session.backwards_clock_steps(events)
    drifting = session.backwards_clock_steps(events, clock=session.iso_instant)
    return {
        len(events),
        len(events) - 1,
        len(backwards),
        len(drifting),
        max(before.unix_second - after.unix_second for before, after in backwards),
    }


def problems(card: str, demo: str, facts: dict[str, Any], figures: set[int]) -> list[str]:
    """Everything the card states that the repository does not say. Empty is the passing case."""
    found: list[str] = []

    block = captured_block(card)
    if block is None:
        found.append("the card has no terminal block, so it shows no captured output at all")
    elif normalised(block) != normalised(demo):
        expected, shown = normalised(demo), normalised(block)
        differing = next(
            (
                n
                for n in range(max(len(expected), len(shown)))
                if expected[n : n + 1] != shown[n : n + 1]
            ),
            0,
        )
        found.append(
            f"the card's terminal block is not the committed capture. Line {differing + 1} reads "
            f"{shown[differing : differing + 1]} and docs/evidence/demo.txt has "
            f"{expected[differing : differing + 1]}"
        )

    shown_facts = facts_shown(card)
    for label, key in FACT_CELLS.items():
        if label not in shown_facts:
            found.append(f"the facts strip has no {label} cell, so that fact is published nowhere")
        elif shown_facts[label] != str(facts[key]):
            found.append(
                f"the card states {shown_facts[label]!r} for {label} and facts.json says "
                f"{str(facts[key])!r}"
            )

    carrying = [sentence for sentence in claim_prose(card) if "backwards" in sentence.lower()]
    if not carrying:
        found.append("no sentence on the card states the claim, so its figures verify nothing")
    for sentence in carrying:
        stated = {int(token.replace(",", "")) for token in FIGURE.findall(sentence)}
        invented = sorted(stated - figures)
        if invented:
            found.append(f"the card states {invented} in {sentence!r}, and nothing measures those")
    return found


def main() -> int:
    if not CARD.exists():
        print("there is no card to check")
        return 0
    card = CARD.read_text(encoding="utf-8")
    demo = (EVIDENCE / "demo.txt").read_text(encoding="utf-8")
    facts = json.loads((EVIDENCE / "facts.json").read_text(encoding="utf-8"))

    found = problems(card, demo, facts, measured_figures())
    for problem in found:
        print(problem, file=sys.stderr)
    if found:
        print("the published card does not match this repository", file=sys.stderr)
        return 1
    print("the card shows the committed capture, the captured facts and measured figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
