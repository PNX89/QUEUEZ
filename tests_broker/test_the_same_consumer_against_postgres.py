"""The same consumer, the same tape, against a real server rather than an embedded library.

WHY THIS EXISTS. The offline suite runs the consumer's real rules against SQLite, which honours
the same transaction semantics, so the rules are genuinely exercised there. What it cannot show
is that the claim survives contact with a client-server database, where the transaction is held
by a process on the other end of a socket and a rollback travels over the wire.

If the atomicity claim were an artefact of an in-process library, this is where it would fail.

THE DIFFERENCES ARE ABSORBED IN A SHIM, HERE, WHERE THEY ARE VISIBLE. PostgreSQL wants `%s`
rather than `?`, and psycopg's cursor is a separate object rather than a return value. The
consumer is written once and neither store's spelling leaks into it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from queuez import consumer, session, tape

DSN = os.environ.get("QUEUEZ_POSTGRES", "postgresql://postgres@127.0.0.1:5432/postgres")
TOPIC = "eqiad.mediawiki.recentchange"


class Shim:
    """One `execute` over psycopg, so the consumer does not know which store it is talking to."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.cursor = connection.cursor()

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> Shim:
        self.cursor.execute(sql.replace("?", "%s"), parameters)
        return self

    def fetchone(self) -> Any:
        return self.cursor.fetchone()


@pytest.fixture
def sink() -> Iterator[Shim]:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("drop table if exists bar, applied cascade")
            # THE WHOLE SCRIPT IN ONE CALL, and splitting it on ";" was a real defect. The
            # schema carries explanatory comments, one of them contained a semicolon, and the
            # split cut a CREATE TABLE in half: `syntax error at end of input`, from a change to
            # a sentence. psycopg runs multiple statements in one execute, so nothing has to
            # parse SQL to apply the schema.
            cursor.execute(consumer.SCHEMA_SQL)
        yield Shim(connection)


@pytest.fixture(scope="module")
def recorded() -> list[session.Event]:
    return session.by_topic(session.read("session_one"))[TOPIC]


def total(sink: Shim) -> int:
    return int(sink.execute("select coalesce(sum(events), 0) from bar").fetchone()[0])


def test_the_rules_behave_the_same_way_against_a_real_server(
    sink: Shim, recorded: list[session.Event]
) -> None:
    """The same counts the offline suite gets, from a database on the other end of a socket."""
    built, injected = tape.build(recorded)
    outcome = consumer.consume(sink, built)

    assert outcome.ignored_as_duplicate == len(injected.resent_offsets)
    assert outcome.applied_as_correction == 1
    assert outcome.never_arrived == injected.gap_offsets
    assert total(sink) == outcome.applied + outcome.applied_as_correction


def test_a_failure_between_the_two_writes_rolls_both_back_here_too(
    sink: Shim, recorded: list[session.Event]
) -> None:
    """The claim, where the transaction is held by another process.

    If atomicity were an artefact of an in-process library rather than a property of the design,
    this is where it would come apart.
    """
    psycopg = pytest.importorskip("psycopg")

    class FailsOnTheSecondWrite:
        def __init__(self, real: Shim) -> None:
            self.real = real
            self.armed = True

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
            if self.armed and "insert into applied" in sql:
                self.armed = False
                raise psycopg.OperationalError("the socket went away between the two writes")
            return self.real.execute(sql, parameters)

    built, _ = tape.build(recorded)
    with pytest.raises(psycopg.OperationalError, match="between the two writes"):
        consumer.consume(FailsOnTheSecondWrite(sink), built)

    folded = total(sink)
    recorded_offsets = int(sink.execute("select count(*) from applied").fetchone()[0])
    assert folded == recorded_offsets, (
        f"{folded} folded events and {recorded_offsets} recorded offsets. They have come apart, "
        f"so the fold and the record of it are not one transaction here"
    )


def test_resuming_from_the_sink_does_not_double_count_against_postgres(
    sink: Shim, recorded: list[session.Event]
) -> None:
    """A replay from behind the stored offset, which is what a broker does after a crash."""
    built, _ = tape.build(recorded)

    consumer.consume(sink, built, stop_after=700)
    resume_from = consumer.stored_offset(sink, TOPIC)
    assert resume_from is not None
    partial = total(sink)

    replayed = [event for event in built if event.offset > resume_from - 100]
    consumer.consume(sink, replayed)
    after_replay = total(sink)

    consumer.consume(sink, built)
    assert total(sink) == after_replay, (
        "a third full pass changed the totals, so the consumer is not idempotent over the whole "
        "tape and the replay above only happened to be safe"
    )
    assert after_replay > partial
