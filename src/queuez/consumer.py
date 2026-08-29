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
    -- BIGINT, AND `integer` WAS WRONG IN A WAY ONLY ONE STORE NOTICED. These offsets are around
    -- 6.46 billion, which does not fit in PostgreSQL's four-byte integer. SQLite's INTEGER is
    -- eight bytes, so the offline suite passed on every one of them and the server rejected the
    -- first with `integer out of range`. A schema that is correct in the store you develop
    -- against and wrong in the one you deploy to is the reason this leg exists.
    offset_seen bigint not null,
    fingerprint text not null,
    primary key (topic, offset_seen)
);
"""


def fingerprint(event: Event) -> str:
    """What the consumer folded on, so a restatement can be told from a redelivery."""
    payload = f"{event.topic}|{event.offset}|{event.domain}|{event.kind}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Outcome:
    """What one pass over a tape did, counted by kind.

    TWO GAP COUNTS, AND ONLY ONE OF THEM IS TRUE. `suspected_on_arrival` is what a detector that
    fires the moment an offset arrives out of step reports. `never_arrived` is what is actually
    missing once the tape has finished.

    They differ, and the difference is not noise: an out-of-order delivery LOOKS exactly like a
    gap at the moment it arrives, and resolves when the offset behind it turns up next. On the
    committed tape, arrival-time detection reports two gaps of which one is not a gap at all.
    Alerting on the first number pages somebody for a feed that is working.
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
    highest: dict[str, int] = {}
    seen_offsets: dict[str, set[int]] = {}

    for index, event in enumerate(events):
        if stop_after is not None and index >= stop_after:
            break

        seen = connection.execute(
            "select fingerprint from applied where topic = ? and offset_seen = ?",
            (event.topic, event.offset),
        ).fetchone()
        current = fingerprint(event)

        if seen is not None and seen[0] == current:
            outcome.ignored_as_duplicate += 1
            continue

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
                insert into applied (topic, offset_seen, fingerprint) values (?, ?, ?)
                on conflict (topic, offset_seen) do update set fingerprint = excluded.fingerprint
                """,
                (event.topic, event.offset, current),
            )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise

        if seen is not None:
            outcome.applied_as_correction += 1
        else:
            outcome.applied += 1

        seen_offsets.setdefault(event.topic, set()).add(event.offset)
        last = highest.get(event.topic)
        if last is not None and event.offset > last + 1:
            assert outcome.suspected_on_arrival is not None
            outcome.suspected_on_arrival.append((last, event.offset))
        highest[event.topic] = max(last or 0, event.offset)

    # THE TRUTH, COMPUTED AFTER THE FACT. Everything between the lowest and highest offset seen
    # that never arrived at all. An out-of-order delivery does not appear here, because by the
    # end it did arrive.
    missing: list[int] = []
    for topic, offsets in seen_offsets.items():
        if not offsets:
            continue
        missing += [
            offset for offset in range(min(offsets), max(offsets) + 1) if offset not in offsets
        ]
        del topic
    outcome.never_arrived = tuple(sorted(missing))

    return outcome


def stored_offset(connection: Any, topic: str) -> int | None:
    """Where to resume from, read out of the sink rather than out of the broker."""
    row = connection.execute(
        "select max(offset_seen) from applied where topic = ?", (topic,)
    ).fetchone()
    return None if row is None or row[0] is None else int(row[0])
