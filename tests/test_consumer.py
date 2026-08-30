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
#: The offset space is the topic AND the partition. Every row of the committed session is 0,
#: which is exactly why the collision below had to be built by hand to be seen at all.
PARTITION = 0


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


def folds_of_an_uninterrupted_run(built: list[session.Event]) -> int:
    """What the tape is worth to a consumer nothing ever interrupts, which is the yardstick."""
    connection = sqlite3.connect(":memory:")
    connection.isolation_level = None
    connection.executescript(consumer.SCHEMA_SQL)
    try:
        consumer.consume(connection, built)
        return totals_of(connection)
    finally:
        connection.close()


def invented(offset: int, partition: int, domain: str = "it.wikipedia.org") -> session.Event:
    """One event that was never recorded, for the two facts the recorded session cannot show.

    Every row of the committed file is partition 0, so a second partition has to be built here.
    The clocks are constant because nothing below reads them.
    """
    return session.Event(
        offset=offset,
        partition=partition,
        topic=TOPIC,
        event_id=f"p{partition}-{offset}",
        domain=domain,
        kind="edit",
        iso_instant="2026-08-29T08:30:11.983Z",
        unix_second=1787992211,
    )


def test_the_recorded_session_is_clean_which_is_why_a_tape_is_invented(
    recorded: list[session.Event],
) -> None:
    """A consumer tested only against a healthy feed has been tested against nothing."""
    assert len(recorded) > 2000
    assert session.sequence_gaps(recorded) == []
    assert session.duplicates(recorded) == []


def test_a_redelivered_offset_is_not_a_gap(recorded: list[session.Event]) -> None:
    """THE ONE INPUT THE GAP DETECTOR WAS NEVER POINTED AT.

    Every call to sequence_gaps in this repository passed the CLEAN recorded session, and the
    invented tape exists precisely to carry what the clean one does not. Pointed at the tape,
    `after.offset != before.offset + 1` reported fourteen gaps: the one that was injected, and
    thirteen redeliveries, where the sorted list puts an offset beside itself and nothing is
    missing at all. Thirteen of the fourteen were exactly what duplicates() reports.
    """
    built, injected = tape.build(recorded)
    assert len(injected.gap_offsets) == tape.GAP_LENGTH
    assert session.duplicates(built), (
        "the tape carries no redelivered offset, so this test has nothing to tell a gap from"
    )

    one_gap = [(injected.gap_offsets[0] - 1, injected.gap_offsets[-1] + 1)]
    assert session.sequence_gaps(built) == one_gap, (
        f"sequence_gaps over the invented tape is not the one injected gap {one_gap}, so it is "
        f"either missing it or reporting a redelivered offset as a hole"
    )


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


def test_the_two_clocks_do_not_agree_about_the_direction_either(
    recorded: list[session.Event],
) -> None:
    """WHICH CLOCK, BECAUSE THE ANSWER IS 547 OR 13 DEPENDING ON THE FIELD READ.

    The count above is about the Unix second in `payload.timestamp`. The same pairs read on the
    ISO instant in `meta.dt` step backwards 13 times by at most 0.012 seconds, which is two
    orders of magnitude away in both count and size. Every figure in this repository said "the
    wall clock" and named neither, and a reader reaching for the millisecond field recomputes 13
    and takes the 547 for invented.

    The showcase pair is the argument in one line: it goes 26 seconds BACKWARDS on one clock and
    forwards on the other, so the two do not even agree about which way time went.
    """
    on_unix = session.backwards_clock_steps(recorded)
    on_iso = session.backwards_clock_steps(recorded, clock=session.iso_instant)
    assert len(on_unix) > 10 * len(on_iso), (
        f"the two clocks now step backwards {len(on_unix)} and {len(on_iso)} times, which is "
        f"close enough that naming the field no longer changes the claim"
    )
    worst_drift = max(session.iso_instant(b) - session.iso_instant(a) for b, a in on_iso)
    assert worst_drift < 1, f"the ISO instant now goes backwards by {worst_drift} seconds"

    before, after = max(on_unix, key=lambda pair: pair[0].unix_second - pair[1].unix_second)
    assert session.iso_instant(after) > session.iso_instant(before), (
        "the worst backwards step on the Unix second no longer goes forwards on the ISO instant, "
        "so the pair the demo prints has stopped showing the two clocks disagreeing"
    )


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
    offset behind it turns up. A monitor wired to the arrival-time count therefore wakes
    somebody up about a feed with nothing wrong with it, which is why both numbers are reported
    and only one of them is the answer.
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
    expected = folds_of_an_uninterrupted_run(built)

    consumer.consume(sink, built, stop_after=700)
    resume_from = consumer.stored_offset(sink, TOPIC, PARTITION)
    assert resume_from is not None

    # NO REWIND HERE ANY MORE, and the hundred that used to be subtracted was the tell. The
    # pointer is the last offset with a complete run behind it, so it is already behind
    # everything still in flight, and replaying what it hands back is what this design exists to
    # survive rather than something a test has to arrange.
    replayed = [event for event in built if event.offset > resume_from]
    consumer.consume(sink, replayed)

    assert totals_of(sink) == expected, (
        f"the interrupted run produced {totals_of(sink)} and the uninterrupted one {expected}, so "
        f"the replay was counted twice"
    )


def test_resuming_inside_the_reorder_window_loses_nothing(
    sink: sqlite3.Connection, recorded: list[session.Event]
) -> None:
    """THE CRASH THE OTHER RESUME TEST STEPS AROUND, and the reason its rewind was there.

    That one stops at tape index 700, three hundred events past the injected reorder, where the
    swap has long since resolved and the largest offset applied is also the last one with a
    complete run behind it. The window where those two differ is the entire difficulty, and it
    is on this tape on purpose. Stopped one event into it, `max(offset_seen)` is ahead of an
    offset still in flight: resuming after it folded 2,022 events where an uninterrupted run
    folds 2,023, and the lost event surfaced as a fourth missing offset on a tape that had three
    removed from it. The old test hid that behind subtracting a hundred from the pointer.
    """
    built, injected = tape.build(recorded)
    expected = folds_of_an_uninterrupted_run(built)

    consumer.consume(sink, built, stop_after=tape.SWAP_AT + 1)
    behind, ahead = injected.swapped_offsets

    def applied(offset: int) -> bool:
        row = sink.execute(
            "select 1 from applied where topic = ? and partition_seen = ? and offset_seen = ?",
            (TOPIC, PARTITION, offset),
        ).fetchone()
        return row is not None

    assert applied(ahead) and not applied(behind), (
        f"the consumer was not stopped inside the reorder window: {behind} and {ahead} were "
        f"swapped on the tape and this test is only about the moment between them"
    )

    resume_from = consumer.stored_offset(sink, TOPIC, PARTITION)
    assert resume_from is not None
    assert resume_from < behind, (
        f"the sink says to resume from {resume_from} and {behind} has not arrived yet, so the "
        f"pointer is ahead of an event still in flight and that event is never applied again"
    )

    consumer.consume(sink, [event for event in built if event.offset > resume_from])
    assert applied(behind), "the event behind the swap was never applied"
    assert totals_of(sink) == expected, (
        f"resuming from the sink folded {totals_of(sink)} events and an uninterrupted run folds "
        f"{expected}, so the crash cost a write"
    )


def test_two_partitions_of_one_topic_do_not_deduplicate_against_each_other(
    sink: sqlite3.Connection,
) -> None:
    """THE FIELD THE READER PARSES AND EVERYTHING DOWNSTREAM THEN IGNORED.

    A topic's offsets are counted within each partition, so the same number in two of them
    names two unrelated events. Keyed on the topic alone, the second one was dropped as a
    redelivery when its content matched and booked as a restatement of the first when it did
    not, which is by_topic's argument about two topics, one layer further down.

    HAND BUILT, BECAUSE THE COMMITTED SESSION CANNOT SHOW THIS. Every row of it is partition 0.
    There is no honest way to observe a collision between two partitions on a feed that has one.
    """
    assert consumer.fingerprint(invented(1, 0)) != consumer.fingerprint(invented(1, 1)), (
        "one offset in two partitions hashes to one fingerprint, so a sink comparing content "
        "cannot tell the second event from a redelivery of the first"
    )

    both = [invented(1, 0), invented(2, 0), invented(3, 0), invented(1, 1), invented(2, 1)]
    outcome = consumer.consume(sink, both)
    assert outcome.applied == len(both), (
        f"{outcome.applied} of {len(both)} events were applied, {outcome.ignored_as_duplicate} "
        f"were dropped as redeliveries and {outcome.applied_as_correction} were booked as "
        f"restatements. Nothing here is either: they are two partitions"
    )
    assert outcome.ignored_as_duplicate == 0
    assert outcome.applied_as_correction == 0
    assert totals_of(sink) == len(both)


def test_a_second_partition_is_not_a_hole_in_the_first(sink: sqlite3.Connection) -> None:
    """The other half of the same defect, and the one that would page somebody.

    Two partitions of a topic sit wherever their own producers have got to, so their offset
    ranges have nothing to do with each other. Merged into one space, the distance between them
    is reported as missing offsets: 1, 2, 3 alongside 900, 901 became 896 offsets that never
    arrived, from a feed with nothing missing at all, plus one suspected gap.
    """
    apart = [invented(1, 0), invented(2, 0), invented(3, 0), invented(900, 1), invented(901, 1)]
    outcome = consumer.consume(sink, apart)

    assert outcome.never_arrived == (), (
        f"the consumer reports {len(outcome.never_arrived)} missing offsets on a tape with "
        f"nothing missing, so it is reading two partitions as one sequence"
    )
    assert outcome.suspected_on_arrival == []
    assert consumer.stored_offset(sink, TOPIC, 0) == 3
    assert consumer.stored_offset(sink, TOPIC, 1) == 901


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


def test_the_schema_applies_as_one_script_rather_than_needing_to_be_split() -> None:
    """A DEFECT CAUSED BY A SENTENCE, which is the reason this is asserted.

    The PostgreSQL fixture used to apply the schema by splitting it on `;`. The schema carries
    comments explaining the two keys, one of them contained a semicolon, and the split cut a
    CREATE TABLE in half. The error was `syntax error at end of input`, from an edit to prose.

    Nothing should have to parse SQL to apply this. Both stores accept the whole script in one
    call, and this checks the property rather than the punctuation.
    """
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(consumer.SCHEMA_SQL)
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
        assert {"bar", "applied"} <= tables
    finally:
        connection.close()
