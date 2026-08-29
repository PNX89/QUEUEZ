"""One breaking change, two settings, and the pair is what makes it evidence."""

from __future__ import annotations

import json
import pathlib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "schema"


def summary() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    return loaded


def test_the_same_change_is_rejected_under_one_setting_and_accepted_under_the_other() -> None:
    """A registry that rejects everything proves nothing about the setting."""
    results = summary()["results"]
    assert results["BACKWARD"]["accepted"] is False
    assert results["NONE"]["accepted"] is True
    assert results["BACKWARD"]["status"] == 409
    assert results["NONE"]["status"] == 200


def test_the_rejection_names_the_actual_incompatibility() -> None:
    """A 409 with no reason is a wall. The reason is what a producer acts on."""
    body = summary()["results"]["BACKWARD"]["body"]
    assert "READER_FIELD_MISSING_DEFAULT_VALUE" in body, (
        f"the registry rejected the change without naming why: {body[:200]}"
    )


def test_the_change_under_test_is_one_that_actually_breaks_a_reader() -> None:
    """A field WITH a default would be compatible, and the exhibit would show nothing."""
    harness = (REPO / "scripts" / "measure_schema.py").read_text(encoding="utf-8")
    assert '"name": "sequence_source", "type": "string"' in harness
    assert '"default"' not in harness, (
        "the added field now carries a default, which is a compatible change, and BACKWARD "
        "would be right to accept it"
    )
    assert summary()["change"] == "a required field with no default"


def test_the_transcript_says_what_happens_under_each_setting() -> None:
    text = (EVIDENCE / "one-change-two-settings.txt").read_text(encoding="utf-8")
    assert "before a single message is" in text
    assert "REJECTED" in text and "ACCEPTED" in text
