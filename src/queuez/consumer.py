"""A consumer that survives at-least-once delivery, and stores its offset with its write.

THE ARGUMENT. A broker that guarantees at-least-once will redeliver, so correctness cannot rest
on each event arriving once. It has to rest on the consumer producing the same result whether an
event arrives once or five times, which means the sink has to know what it has already applied.

WHERE THE OFFSET LIVES, AND IT IS THE WHOLE POINT. The offset is a ROW IN THE SINK, written in
the same transaction as the fold it belongs to. The broker's own offset store is not the source
of truth here. If the process dies between applying a write and telling the broker, the broker
replays; the sink already knows it applied that offset and ignores it. If the offset were
committed separately, that same crash loses the write and keeps the acknowledgement, which is
the failure everybody describes as "we lost a message" without being able to say when.

A CORRECTION IS NOT A DUPLICATE. Both arrive as an offset already seen. A duplicate carries the
same content and must be dropped; a correction carries different content and must be applied.
Deduplicating on the offset alone silently discards the second, so the fingerprint of the
content is stored beside the offset and the two cases are separated by comparing it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from .session import Event

SCHEMA_SQL = """
create table if not exists bar (
    topic  text not null,
    domain text not null,
    events bigint not null,
    primary key (topic, domain)
);
create table if not exists applied (
    topic       text not null,
    -- THE PARTITION IS PART OF THE OFFSET, AND LEAVING IT OUT WAS A SILENT COLLISION. Offsets
    -- are per partition, so offset 1 of partition 0 and offset 1 of partition 1 are two
    -- different events in two different sequences. Keyed on the topic alone, the second of that
    -- pair was read as a redelivery when its content matched and as a restatement when it did
    -- not, and the missing-offset count filled with the distance between the two partitions'
    -- ranges. Every row of the committed session is partition 0, so nothing in the suite could
    -- see it and the first multi-partition topic would have.
    --
    -- Named `partition_seen` for the same reason as `offset_seen`: both words are keywords in
    -- these stores, and a column nobody has to quote is worth more than the shorter name.
    partition_seen integer not null,
    -- BIGINT, AND `integer` WAS WRONG IN A WAY ONLY ONE STORE NOTICED. These offsets are around
    -- 6.46 billion, which does not fit in PostgreSQL's four-byte integer. SQLite's INTEGER is
    -- eight bytes, so the offline suite passed on every one of them and the server rejected the
    -- first with `integer out of range`. A schema that is correct in the store you develop
    -- against and wrong in the one you deploy to is the reason this leg exists.
    offset_seen bigint not null,
    fingerprint text not null,
    -- THE FINGERPRINT IS PART OF THE KEY, AND KEEPING IT OUT WAS A REAL DEFECT.
    --
    -- The first version stored one row per offset and overwrote the fingerprint when a
    -- correction arrived. That is not idempotent under replay, which at-least-once delivery
    -- guarantees will happen: on a second pass the ORIGINAL arrives, differs from the stored
    -- correction, and is applied as a correction of it; then the correction arrives, differs
    -- again, and is applied too. Every full replay added two folds, for ever, oscillating.
    --
    -- Recording every distinct content seen for an offset fixes it by construction. A
    -- fingerprint already present is a redelivery whatever order it arrives in, and a
    -- fingerprint never seen is a restatement. Replay is then free.
    primary key (topic, partition_seen, offset_seen, fingerprint)
);
"""


def fingerprint(event: Event) -> str:
    """What the consumer folded on, so a restatement can be told from a redelivery.

    The partition is in here as well as in the key, because two events from two partitions of
    one topic are two events even when everything else about them matches, and a function that
    hands back the same digest for both is a trap laid for whoever reads it next.
    """
    payload = f"{event.topic}|{event.partition}|{event.offset}|{event.domain}|{event.kind}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Outcome:
    """What one pass over a tape did, counted by kind.

    TWO GAP COUNTS, AND ONLY ONE OF THEM IS TRUE. `suspected_on_arrival` is what a detector that
    fires the moment an offset arrives out of step reports. `never_arrived` is what is actually
    missing once the tape has finished.

    They differ, and the difference is not noise: an out-of-order delivery LOOKS exactly like a
    gap at the moment it arrives, and resolves when the offset behind it turns up next. On the
    committed tape, arrival-time detection reports two gaps of which one is not a gap at all,
    which is what the example prints and what the README argues from.

    BOTH ARE COUNTED PER (TOPIC, PARTITION), because that pair is the offset space. They are
    reported flattened, as offsets and as pairs of offsets, so a reader wanting to know which
    space one came from has to go back to the tape for it.
    """

    applied: int = 0
    ignored_as_duplicate: int = 0
    applied_as_correction: int = 0
    suspected_on_arrival: list[tuple[int, int]] | None = None
    never_arrived: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.suspected_on_arrival is None:
            self.suspected_on_arrival = []


def consume(connection: Any, events: Iterable[Event], *, stop_after: int | None = None) -> Outcome:
    """Fold a tape into the sink, one transaction per event, and report what happened.

    `stop_after` exists so a test can kill the consumer mid-tape and restart it. It stops
    BETWEEN transactions, which is the honest place: a crash inside one is what the transaction
    is for, and a crash between them is what the stored offset is for.
    """
    outcome = Outcome()
    # KEYED ON THE OFFSET SPACE, WHICH IS THE TOPIC AND THE PARTITION TOGETHER. Keyed on the
    # topic alone these three counters read two partitions as one sequence, which is the same
    # mistake as merging two topics and by_topic already refuses to make it.
    highest: dict[tuple[str, int], int] = {}
    seen_offsets: dict[tuple[str, int], set[int]] = {}

    for index, event in enumerate(events):
        if stop_after is not None and index >= stop_after:
            break

        space = (event.topic, event.partition)
        current = fingerprint(event)
        already = connection.execute(
            "select 1 from applied where topic = ? and partition_seen = ? and offset_seen = ?"
            " and fingerprint = ?",
            (event.topic, event.partition, event.offset, current),
        ).fetchone()
        if already is not None:
            outcome.ignored_as_duplicate += 1
            continue

        # A different content for an offset already applied is a restatement rather than a
        # redelivery. This is read BEFORE the write below, so the count is of what arrived
        # rather than of what the table happens to hold afterwards.
        seen_before = connection.execute(
            "select 1 from applied where topic = ? and partition_seen = ? and offset_seen = ?",
            (event.topic, event.partition, event.offset),
        ).fetchone()

        # ONE TRANSACTION, TWO WRITES. The fold and the record of having folded it are the same
        # commit, so no crash can separate them.
        connection.execute("begin")
        try:
            connection.execute(
                """
                insert into bar (topic, domain, events) values (?, ?, 1)
                on conflict (topic, domain) do update set events = bar.events + 1
                """,
                (event.topic, event.domain),
            )
            connection.execute(
                """
                insert into applied (topic, partition_seen, offset_seen, fingerprint)
                values (?, ?, ?, ?)
                on conflict (topic, partition_seen, offset_seen, fingerprint) do nothing
                """,
                (event.topic, event.partition, event.offset, current),
            )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise

        if seen_before is not None:
            outcome.applied_as_correction += 1
        else:
            outcome.applied += 1

        seen_offsets.setdefault(space, set()).add(event.offset)
        last = highest.get(space)
        if last is not None and event.offset > last + 1:
            assert outcome.suspected_on_arrival is not None
            outcome.suspected_on_arrival.append((last, event.offset))
        highest[space] = max(last or 0, event.offset)

    # THE TRUTH, COMPUTED AFTER THE FACT. Everything between the lowest and highest offset seen
    # that never arrived at all. An out-of-order delivery does not appear here, because by the
    # end it did arrive.
    #
    # WALKED AS PAIRS RATHER THAN OVER `range(min, max)`. The list is then proportional to what
    # is actually missing rather than to the distance between the ends, and these offsets start
    # at six and a half billion: one partition read as two spaces, or one truly wide split, and
    # the old form allocated a list the size of the span to find three holes in it.
    missing: list[int] = []
    for offsets in seen_offsets.values():
        missing += [
            absent
            for lower, upper in pairwise(sorted(offsets))
            for absent in range(lower + 1, upper)
        ]
    outcome.never_arrived = tuple(sorted(missing))

    return outcome


def stored_offset(connection: Any, topic: str, partition: int) -> int | None:
    """Where to resume from, read out of the sink rather than out of the broker.

    THE HIGHEST OFFSET WITH NOTHING UNAPPLIED BELOW IT, and `max(offset_seen)` was the wrong
    answer to that question. Out-of-order delivery is one of the four failures the tape injects
    on purpose, and in that window the largest offset applied sits AHEAD of the last one with a
    complete run behind it. Resume after the maximum and the event the reorder left behind is
    below the pointer for ever: on the committed tape, crashing on the swap and resuming at the
    maximum folded 2,022 events where an uninterrupted run folds 2,023, and the lost offset
    showed up as a fourth entry in a list of missing offsets that only ever had three.

    RESUMING FROM HERE REPLAYS, AND THAT IS THE POINT RATHER THAN THE PRICE. A permanent gap
    pins this pointer behind it, because the sink cannot tell an offset that never arrived from
    one still in flight and guessing the first loses a write. What that costs is redelivery of
    everything after the hole, and redelivery is free here by construction: the fingerprint is
    part of the key, so a second pass over the whole tape applies nothing.
    """
    cursor = connection.execute(
        "select offset_seen from applied where topic = ? and partition_seen = ?"
        " order by offset_seen",
        (topic, partition),
    )
    contiguous: int | None = None
    while (row := cursor.fetchone()) is not None:
        offset = int(row[0])
        if contiguous is None or offset == contiguous + 1:
            contiguous = offset
        elif offset > contiguous + 1:
            break
        # An offset equal to the one before it is the same offset under a second fingerprint,
        # which is a correction rather than a step, so the run continues through it.
    return contiguous
