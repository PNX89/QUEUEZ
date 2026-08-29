"""What the consumer does about the four failures, and what a crash does to it.

The claim being defended is not that the consumer works. It is that it produces the same sink
whether an event arrives once or twice, that it can tell a restatement from a redelivery, that
it knows what never arrived, and that killing it between two writes costs nothing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from queuez import consumer, session, tape

TOPIC = "eqiad.mediawiki.recentchange"


@pytest.fixture
def sink() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    connection.isolation_level = None
    try:
        connection.executescript(consumer.SCHEMA_SQL)
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="module")
def recorded() -> list[session.Event]:
    return session.by_topic(session.read("session_one"))[TOPIC]


def totals_of(connection: sqlite3.Connection) -> int:
    return int(connection.execute("select sum(events) from bar").fetchone()[0] or 0)


def test_the_recorded_session_is_clean_which_is_why_a_tape_is_invented(
    recorded: list[session.Event],
) -> None:
    """A consumer tested only against a healthy feed has been tested against nothing."""
    assert len(recorded) > 2000
    assert session.sequence_gaps(recorded) == []
    assert session.duplicates(recorded) == []


def test_the_clock_goes_backwards_on_the_real_feed_and_the_sequence_does_not(
    recorded: list[session.Event],
) -> None:
    """THE MEASUREMENT THE WHOLE REPOSITORY RESTS ON.

    Every rule here asserts on sequence continuity and none looks at a clock. That is not a
    principle, it is this number: in offset order, on a real public feed recorded once, the wall
    clock steps backwards hundreds of times.
    """
    backwards = session.backwards_clock_steps(recorded)
    assert len(backwards) > 100, (
        f"the clock only went backwards {len(backwards)} times in this session, so the argument "
        f"for ignoring it is weaker than the README says"
    )
    worst = max(before.unix_second - after.unix_second for before, after in backwards)
    assert worst >= 10, f"the largest backwards step is {worst} seconds"
    assert session.sequence_gaps(recorded) == [], "the sequence is not monotone in this session"


def test_the_two_clocks_in_one_payload_disagree_and_never_in_the_other_direction(
    recorded: list[session.Event],
) -> None:
    """Two timestamps, one event, and one is never the earlier of the two."""
    gaps = [event.clock_gap_seconds for event in recorded]
    disagreeing = [gap for gap in gaps if abs(gap) >= 1]
    assert len(disagreeing) > len(recorded) // 3
    assert min(gaps) >= 0, (
        "the ISO instant is now sometimes EARLIER than the unix second, which is a change in the "
        "feed worth reading about rather than a test to relax"
    )


def test_a_resent_window_does_not_double_the_totals(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """At-least-once delivery means this happens, not that it might."""
    built, injected = tape.build(recorded)
    outcome = consumer.consume(sink, built)
    assert outcome.ignored_as_duplicate == len(injected.resent_offsets)
    assert totals_of(sink) == outcome.applied + outcome.applied_as_correction


def test_a_correction_is_applied_and_a_duplicate_is_not(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """The pair that look identical to a consumer reading offsets alone."""
    built, injected = tape.build(recorded)
    outcome = consumer.consume(sink, built)
    assert outcome.applied_as_correction == 1, (
        "the correction was not applied, so a restatement of an already consumed record is being "
        "discarded as a duplicate"
    )
    corrected = sink.execute("select count(*) from bar where domain like 'corrected.%'").fetchone()[
        0
    ]
    assert corrected == 1
    assert injected.corrected_offset > 0


def test_the_consumer_knows_what_never_arrived_and_not_merely_what_looked_late(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """TWO GAP COUNTS AND ONLY ONE IS TRUE.

    An out-of-order delivery looks exactly like a gap when it arrives and resolves when the
    offset behind it turns up. Alerting on the arrival-time count pages somebody for a feed
    that is working.
    """
    built, injected = tape.build(recorded)
    outcome = consumer.consume(sink, built)
    assert outcome.never_arrived == injected.gap_offsets, (
        f"the consumer reports {outcome.never_arrived} missing and {injected.gap_offsets} were "
        f"removed from the tape"
    )
    assert outcome.suspected_on_arrival is not None
    assert len(outcome.suspected_on_arrival) > 1, (
        "arrival-time detection found no false positive on a tape carrying an out-of-order "
        "delivery, so the distinction this repository draws has no example in it"
    )


def test_killing_the_consumer_between_writes_costs_nothing(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """THE CLAIM ABOUT THE OFFSET LIVING IN THE SINK.

    The consumer is stopped part way, restarted from what the SINK says it applied rather than
    from anything the broker holds, and the totals have to come out the same as an uninterrupted
    run. If the offset were committed separately, this is where a write is lost while its
    acknowledgement survives.
    """
    built, _ = tape.build(recorded)

    uninterrupted = sqlite3.connect(":memory:")
    uninterrupted.isolation_level = None
    uninterrupted.executescript(consumer.SCHEMA_SQL)
    try:
        consumer.consume(uninterrupted, built)
        expected = totals_of(uninterrupted)
    finally:
        uninterrupted.close()

    consumer.consume(sink, built, stop_after=700)
    resume_from = consumer.stored_offset(sink, TOPIC)
    assert resume_from is not None

    # The broker replays from the last acknowledged offset, which after a crash is BEHIND where
    # the sink actually got to. Replaying a hundred events it has already applied is exactly the
    # case this design exists to survive.
    replayed = [event for event in built if event.offset > resume_from - 100]
    consumer.consume(sink, replayed)

    assert totals_of(sink) == expected, (
        f"the interrupted run produced {totals_of(sink)} and the uninterrupted one {expected}, so "
        f"the replay was counted twice"
    )


def test_offsets_from_two_origins_are_never_compared(recorded: list[session.Event]) -> None:
    """The two topics run in entirely different ranges, so merging them by offset interleaves
    them by an accident of where each origin happened to be."""
    grouped = session.by_topic(session.read("session_one"))
    assert len(grouped) == 2
    ranges = {
        topic: (min(e.offset for e in events), max(e.offset for e in events))
        for topic, events in grouped.items()
    }
    spans = sorted(ranges.values())
    assert spans[0][1] < spans[1][0], (
        f"the two topics' offset ranges now overlap: {ranges}. They are still different spaces "
        f"and must not be compared, but this test can no longer show it"
    )


def test_a_failure_between_the_two_writes_rolls_both_back(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """THE TEST A MUTATION SAID WAS MISSING, and it is the repository's central claim.

    Moving the offset write to AFTER the commit left every other test here passing. They all
    stop the consumer between transactions, which is the easy crash: the sink is consistent
    whatever order the two writes are in. The crash that separates them is the one INSIDE, and
    the only reason it cannot happen is that they are one transaction.

    So the second write is made to fail, and what is asserted is that the first one did not
    survive it. With the two in one transaction the fold is rolled back and the event is
    reprocessed on the next pass. With them apart, the bar keeps a fold that nothing records
    having applied, and the next pass applies it again: a double count with no crash in sight.
    """

    class FailsOnTheSecondWrite:
        """A connection that refuses exactly one statement, and otherwise gets out of the way."""

        def __init__(self, real: sqlite3.Connection) -> None:
            self.real = real
            self.armed = True

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
            if self.armed and "insert into applied" in sql:
                self.armed = False
                raise sqlite3.OperationalError("the disk went away between the two writes")
            return self.real.execute(sql, parameters)

    built, _ = tape.build(recorded)
    guarded = FailsOnTheSecondWrite(sink)

    with pytest.raises(sqlite3.OperationalError, match="between the two writes"):
        consumer.consume(guarded, built)

    folded = int(sink.execute("select coalesce(sum(events), 0) from bar").fetchone()[0])
    recorded_offsets = int(sink.execute("select count(*) from applied").fetchone()[0])
    assert folded == recorded_offsets, (
        f"the sink holds {folded} folded events and {recorded_offsets} recorded offsets. They "
        f"have come apart, which means the fold and the record of it are not in one transaction "
        f"and a crash between them loses one or duplicates the other"
    )


def test_the_offset_column_can_hold_the_offsets_this_feed_actually_uses() -> None:
    """A DEFECT ONE STORE COULD NOT SEE, and the reason the second store leg exists.

    The offsets in the committed session are around 6.46 billion. SQLite's INTEGER is eight
    bytes so every test here passed; PostgreSQL's `integer` is four, and it rejected the first
    row with `integer out of range`. The schema is one string used by both, and it now says
    `bigint`, which both accept.

    This asserts the schema rather than the behaviour, because the behaviour is only observable
    in the store that has the narrower type.
    """
    assert "offset_seen bigint not null" in consumer.SCHEMA_SQL, (
        "the offset column is no longer bigint, and a four-byte integer cannot hold the offsets "
        "in the committed session"
    )
    largest = max(event.offset for event in session.read("session_one"))
    assert largest > 2**31 - 1, (
        f"the largest offset in the committed session is {largest}, which now fits in a "
        f"four-byte integer, so this test no longer demonstrates anything"
    )


def test_replaying_the_whole_tape_a_third_time_changes_nothing(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """THE TEST THAT FOUND THE REAL DEFECT, and it found it in the PostgreSQL leg first.

    The offline replay test above replays a SUFFIX, which is what a broker does after a crash,
    and that passed against a consumer that was not idempotent at all. Replaying the whole tape
    is the harder question and at-least-once delivery makes it a real one.

    What it caught: storing one fingerprint per offset and overwriting it on a correction
    oscillates. On the second pass the ORIGINAL arrives, differs from the stored correction, and
    is applied as a correction of it; then the correction arrives, differs again, and is applied
    too. Every full replay added two folds, for ever.
    """
    built, _ = tape.build(recorded)
    totals = []
    for _ in range(3):
        consumer.consume(sink, built)
        totals.append(totals_of(sink))
    assert len(set(totals)) == 1, (
        f"three full passes gave {totals}, so the consumer is not idempotent over the whole tape "
        f"and a broker replaying from behind would inflate the sink"
    )


def test_a_replay_reports_everything_as_a_duplicate_and_nothing_as_a_correction(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """The counts, not just the totals. A pass that applied nothing but called it a correction
    would leave the sink right and the ledger wrong."""
    built, _ = tape.build(recorded)
    consumer.consume(sink, built)
    second = consumer.consume(sink, built)
    assert second.applied == 0
    assert second.applied_as_correction == 0
    assert second.ignored_as_duplicate == len(built)
