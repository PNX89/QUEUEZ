"""Reading a recorded session, and the two orderings that disagree about it.

THE CLAIM THIS REPOSITORY IS BUILT ON. A feed's SEQUENCE is the only ordering a consumer can
trust. Its clock is not, and this is not a caution: on a real public stream, recorded once and
committed here, the Unix second in `payload.timestamp` goes BACKWARDS between consecutive events
547 times out of 2,024, by as much as 26 seconds, while the offset is monotone throughout.

A gap detector built on time therefore reports gaps that are not there and misses the ones that
are. Every rule in this repository asserts on sequence continuity and none of them looks at a
clock, and the reason is a number rather than a principle.

WHICH CLOCK, BECAUSE THE PAYLOAD CARRIES TWO AND THEY DISAGREE ABOUT DIRECTION. Read on the ISO
instant in `meta.dt` instead, the same 2,024 pairs step backwards 13 times by at most 0.012
seconds. Both figures are correct and they are about different fields, so a count stated without
naming its field invites the reader who reaches for the other one to recompute 13 and conclude
the 547 was picked. Every count here says which clock it read.

THE TWO ALSO DISAGREE ABOUT SIZE, which is the other half. They differ on 1,576 of 2,027 events,
the ISO instant is never the earlier of the two, and the gap runs from 0.036 seconds to 27.5.
This repository does not assert why, because the archive records what a publisher emitted and
not what it was doing: what is measured is the direction and the size.
"""

from __future__ import annotations

import csv
import datetime
import pathlib
from collections.abc import Callable
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


def unix_second(event: Event) -> float:
    """One of the two clocks: `payload.timestamp` at capture, a whole second."""
    return float(event.unix_second)


def iso_instant(event: Event) -> float:
    """The other: `meta.dt` at capture, read as a Unix timestamp so the two are comparable."""
    return event.instant.timestamp()


def backwards_clock_steps(
    events: list[Event], *, clock: Callable[[Event], float] = unix_second
) -> list[tuple[Event, Event]]:
    """Consecutive pairs, in SEQUENCE order, where the NAMED clock goes backwards.

    THE CLOCK IS AN ARGUMENT BECAUSE THE ANSWER DIFFERS BY TWO ORDERS OF MAGNITUDE. On the
    committed session the Unix second steps backwards 547 times by as much as 26 seconds and the
    ISO instant 13 times by at most 0.012. This defaulted to the Unix second and said "the wall
    clock", which is the field it does not name, and every figure downstream inherited that.
    """
    ordered = sorted(events, key=lambda event: event.offset)
    return [(before, after) for before, after in pairwise(ordered) if clock(after) < clock(before)]


def sequence_gaps(events: list[Event]) -> list[tuple[int, int]]:
    """Offsets missing between consecutive events, as (before, after) pairs.

    This is the only kind of gap this repository recognises. It is a statement about the
    sequence and it needs no clock at all.

    STRICTLY GREATER, AND `!=` WAS WRONG IN A WAY THE RECORDED SESSION COULD NOT SHOW. The list
    is sorted by offset, so a redelivered offset sits next to itself, and `!=` calls that a gap
    when nothing is missing at all. On the invented tape, which is the only input here that
    carries redeliveries, it reported fourteen gaps where one was injected, and thirteen of the
    fourteen were exactly the offsets duplicates() reports. Every call site passed the clean
    recorded session, so the one input that would have shown it was never handed to it.

    The pairs are (before, after), which is the order the comprehension below builds them in.
    This docstring promised the opposite, so a caller unpacking one got the endpoints reversed.
    """
    ordered = sorted(events, key=lambda event: event.offset)
    return [
        (before.offset, after.offset)
        for before, after in pairwise(ordered)
        if after.offset > before.offset + 1
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
