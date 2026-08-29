"""Reading a recorded session, and the two orderings that disagree about it.

THE CLAIM THIS REPOSITORY IS BUILT ON. A feed's SEQUENCE is the only ordering a consumer can
trust. Its clock is not, and this is not a caution: on a real public stream, recorded once and
committed here, the wall clock goes BACKWARDS between consecutive events 547 times out of 2,024,
by as much as 26 seconds, while the offset is monotone throughout.

A gap detector built on time therefore reports gaps that are not there and misses the ones that
are. Every rule in this repository asserts on sequence continuity and none of them looks at a
clock, and the reason is a number rather than a principle.

TWO CLOCKS IN ONE PAYLOAD, which is the other half. Each event carries an ISO instant with
milliseconds and a Unix second, and they disagree on 1,576 of 2,027 events. The ISO instant is
never the earlier of the two, and the gap runs from 0.036 seconds to 27.5. This repository does
not assert why, because the archive records what a publisher emitted and not what it was doing:
what is measured is the direction and the size.
"""

from __future__ import annotations

import csv
import datetime
import pathlib
from dataclasses import dataclass
from itertools import pairwise

DATA = pathlib.Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Event:
    """One recorded event, reduced to the facts that carry no licence with them."""

    offset: int
    partition: int
    topic: str
    event_id: str
    domain: str
    kind: str
    iso_instant: str
    unix_second: int

    @property
    def instant(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self.iso_instant.replace("Z", "+00:00"))

    @property
    def clock_gap_seconds(self) -> float:
        """How far the ISO instant sits after the Unix second, in seconds."""
        return self.instant.timestamp() - self.unix_second


def read(name: str) -> list[Event]:
    """A recorded session, in the order it arrived."""
    path = DATA / f"{name}.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            Event(
                offset=int(row["offset"]),
                partition=int(row["partition"]),
                topic=row["topic"],
                event_id=row["event_id"],
                domain=row["domain"],
                kind=row["kind"],
                iso_instant=row["iso_instant"],
                unix_second=int(row["unix_second"]),
            )
            for row in csv.DictReader(handle)
        ]


def by_topic(events: list[Event]) -> dict[str, list[Event]]:
    """Split by origin, because two origins have two offset spaces.

    THE OFFSETS ARE NOT COMPARABLE ACROSS TOPICS and treating them as one sequence is a
    ready-made defect. In the committed session the two run in entirely different ranges, so a
    consumer that sorted the merged stream by offset would interleave them by an accident of
    where each origin happened to be.
    """
    grouped: dict[str, list[Event]] = {}
    for event in events:
        grouped.setdefault(event.topic, []).append(event)
    return grouped


def backwards_clock_steps(events: list[Event]) -> list[tuple[Event, Event]]:
    """Consecutive pairs, in SEQUENCE order, where the wall clock goes backwards."""
    ordered = sorted(events, key=lambda event: event.offset)
    return [
        (before, after)
        for before, after in pairwise(ordered)
        if after.unix_second < before.unix_second
    ]


def sequence_gaps(events: list[Event]) -> list[tuple[int, int]]:
    """Offsets missing between consecutive events, as (after, before) pairs.

    This is the only kind of gap this repository recognises. It is a statement about the
    sequence and it needs no clock at all.
    """
    ordered = sorted(events, key=lambda event: event.offset)
    return [
        (before.offset, after.offset)
        for before, after in pairwise(ordered)
        if after.offset != before.offset + 1
    ]


def duplicates(events: list[Event]) -> list[int]:
    """Offsets delivered more than once, which at-least-once delivery guarantees will happen."""
    seen: dict[int, int] = {}
    for event in events:
        seen[event.offset] = seen.get(event.offset, 0) + 1
    return sorted(offset for offset, count in seen.items() if count > 1)


def normalised(events: list[Event]) -> list[str]:
    """The normalised series, as lines, and the format is a contract between two languages.

    A second implementation of this exists in Rust, reading the same committed file, and a
    conformance suite compares the two outputs line by line. Neither is the reference: they
    either agree or the suite fails.

    The format is deliberately dull. Padding, locale-aware formatting or a float would each be a
    difference the suite would find and nobody would want.
    """
    return [f"{e.offset}|{e.topic}|{e.domain}|{e.kind}" for e in events]
