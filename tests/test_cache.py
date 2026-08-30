"""A cache under a stampede, and a default that stops it being a cache at all."""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "cache"
sys.path.insert(0, str(REPO / "scripts"))


class FakeStore:
    """Records the exact command sequence, so a check hiding before the set has nowhere to go."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self._keys: set[str] = set()

    def get(self, key: str) -> bytes | None:
        self.calls.append(("get", key, False))
        return b"1" if key in self._keys else None

    def set(self, key: str, value: bytes, nx: bool = False, ex: int | None = None) -> bool:
        self.calls.append(("set", key, nx))
        if nx and key in self._keys:
            return False
        self._keys.add(key)
        return True


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
    """A check followed by a set races, and the race is the whole failure.

    GREPPING THE HARNESS FOR THE STRINGS "nx=True" AND "would race" USED TO BE THIS TEST'S WHOLE
    BODY. Both strings survive as comments even after the lease is replaced by a get-then-set
    race, so a keyword left in prose kept the test green over a harness that no longer had the
    property the keyword names. Driving the function with a fake store and inspecting the exact
    calls it made proves the property instead of trusting a comment to describe it.
    """
    from measure_cache import take_the_lease

    store = FakeStore()
    first = take_the_lease(store, "quote:x")
    second = take_the_lease(store, "quote:x")
    assert first is True
    assert second is False, "a second caller taking the lease means it is not exclusive"

    lease_key = "lease:quote:x"
    assert not any(call == ("get", lease_key, False) for call in store.calls), (
        "a GET on the lease key before the SET is exactly the check-then-set race this "
        "function exists to prevent, atomic winner or not"
    )
    sets_on_lease_key = [call for call in store.calls if call[0] == "set" and call[1] == lease_key]
    assert len(sets_on_lease_key) == 2
    assert all(nx is True for _, _, nx in sets_on_lease_key), (
        "every attempt to take the lease has to ask the store for NX: that is what makes the "
        "store, rather than this process, the one that decides the single winner"
    )
