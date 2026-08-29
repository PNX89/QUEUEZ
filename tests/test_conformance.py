"""Two implementations of one normalisation, and what the comparison has to be worth."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from queuez import session

REPO = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "conformance"


def summary() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    return loaded


def test_the_two_implementations_agreed_on_every_line() -> None:
    numbers = summary()
    assert numbers["identical"] is True
    assert numbers["events"] == len(session.read("session_one")), (
        "the conformance run covered a different number of events than the committed session "
        "holds, so it was comparing something else"
    )


def test_the_comparison_covers_the_whole_file_rather_than_a_sample() -> None:
    """A conformance suite over the first hundred lines is a conformance suite over nothing."""
    assert summary()["events"] > 2000


def test_neither_implementation_is_named_as_the_reference() -> None:
    """The property that makes the agreement mean something.

    If one were the reference, the other's job would be to reproduce its bugs, and a
    disagreement would be resolved by asking which one is older.
    """
    harness = (REPO / "scripts" / "measure_conformance.py").read_text(encoding="utf-8")
    assert "Neither is the reference" in harness or "NEITHER IS THE REFERENCE" in harness
    text = (EVIDENCE / "two-implementations.txt").read_text(encoding="utf-8")
    assert "Neither implementation is the reference" in text


def test_the_timing_is_published_with_what_it_is_worth() -> None:
    """A throughput figure with no caveat is a throughput claim."""
    numbers = summary()
    assert numbers["python_seconds"] > 0
    assert numbers["rust_seconds"] > 0
    assert "representative of nothing" in numbers["note"]
    text = (EVIDENCE / "two-implementations.txt").read_text(encoding="utf-8")
    assert "representative" in text


def test_the_rust_side_checks_the_header_rather_than_assuming_the_columns() -> None:
    """A column inserted upstream would otherwise shift every field silently."""
    source = (REPO / "decoder" / "src" / "main.rs").read_text(encoding="utf-8")
    assert "EXPECTED_HEADER" in source
    assert "the header has moved" in source


def test_the_decoder_has_no_dependencies() -> None:
    """Otherwise the conformance suite compares two wrappers around somebody else's parser."""
    manifest = (REPO / "decoder" / "Cargo.toml").read_text(encoding="utf-8")
    body = manifest.split("[dependencies]")[1].split("[")[0]
    assert not [line for line in body.splitlines() if line.strip() and not line.startswith("#")], (
        f"the decoder has taken a dependency: {body.strip()}"
    )
