"""A cache under a stampede, and a default that stops it being a cache at all."""

from __future__ import annotations

import json
import pathlib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "cache"


def summary() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    return loaded


def test_the_stampede_happened_before_it_was_prevented() -> None:
    """Single flight preventing nothing is not evidence of single flight."""
    numbers = summary()
    assert numbers["recomputed_without_single_flight"] > numbers["recomputed_with_single_flight"]
    assert numbers["recomputed_without_single_flight"] >= numbers["callers"] // 2, (
        f"only {numbers['recomputed_without_single_flight']} of {numbers['callers']} callers "
        f"recomputed, so the stampede barely happened and the comparison is thin"
    )


def test_single_flight_leaves_exactly_one_caller_computing() -> None:
    """Two winners means the lease is racy, which is the bug it exists to prevent."""
    assert summary()["recomputed_with_single_flight"] == 1


def test_the_default_policy_is_the_one_that_refuses_writes() -> None:
    """The finding, and it is about a default rather than about a mistake."""
    numbers = summary()
    assert numbers["default_maxmemory_policy"] == "noeviction", (
        f"this server starts with {numbers['default_maxmemory_policy']}, so the argument about "
        f"the default needs re-reading rather than restating"
    )
    assert numbers["write_refused_under_noeviction"] == "OutOfMemoryError"


def test_the_lease_is_taken_atomically_rather_than_checked_and_then_set() -> None:
    """A check followed by a set races, and the race is the whole failure."""
    harness = (REPO / "scripts" / "measure_cache.py").read_text(encoding="utf-8")
    assert "nx=True" in harness
    assert "would race" in harness
