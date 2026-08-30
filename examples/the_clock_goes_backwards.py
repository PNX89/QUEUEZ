"""What a recorded feed does to a consumer that trusts the clock, and to one that does not.

    uv run python examples/the_clock_goes_backwards.py

NO BROKER, NO DATABASE SERVER, NO NETWORK. The consumer's real rules run against the committed
session and SQLite, which honours the same transaction semantics the whole argument rests on.
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from queuez import consumer, session, tape

TOPIC = "eqiad.mediawiki.recentchange"


def main() -> None:
    events = session.by_topic(session.read("session_one"))[TOPIC]

    # BOTH CLOCKS, BECAUSE ONE COUNT WITHOUT ITS FIELD IS A NUMBER A READER CANNOT CHECK. This
    # printed 547 and called it "the wall clock". The payload has two, and a reader reaching for
    # the millisecond one recomputes 13 and concludes the 547 was picked. They are both true.
    backwards = session.backwards_clock_steps(events)
    worst = max(before.unix_second - after.unix_second for before, after in backwards)
    drifting = session.backwards_clock_steps(events, clock=session.iso_instant)
    worst_drift = max(session.iso_instant(b) - session.iso_instant(a) for b, a in drifting)

    print(f"{len(events)} events, recorded from a real public feed, in offset order.")
    print()
    print(f"  the sequence is monotone with {len(session.sequence_gaps(events))} gaps")
    print(f"  the Unix second in payload.timestamp goes BACKWARDS {len(backwards)} times,")
    print(f"  by up to {worst} seconds. The ISO instant in meta.dt goes backwards")
    print(f"  {len(drifting)} times, by up to {worst_drift:.3f} seconds.")
    print()
    before, after = max(backwards, key=lambda pair: pair[0].unix_second - pair[1].unix_second)
    print(f"  offset {before.offset} says {before.unix_second} and {before.iso_instant}")
    print(f"  offset {after.offset} says {after.unix_second} and {after.iso_instant}")
    step = session.iso_instant(after) - session.iso_instant(before)
    print(f"  so the Unix second went back {worst} seconds there while the ISO instant")
    print(f"  went FORWARD {step:.3f} seconds. They disagree about the direction too.")
    print()
    print("  A gap detector built on time reports gaps that are not there and misses the")
    print("  ones that are. Every rule here asserts on the sequence and none looks at a clock.")
    print()

    gaps = [e.clock_gap_seconds for e in events]
    disagree = sum(1 for gap in gaps if abs(gap) >= 1)
    print(f"The two also disagree about size, on {disagree} of {len(events)} events:")
    print(f"  the ISO instant sits between {min(gaps):.3f}s and {max(gaps):.1f}s after the")
    print("  Unix second, and never before it.")
    print()

    built, injected = tape.build(events)
    connection = sqlite3.connect(":memory:")
    try:
        connection.isolation_level = None
        connection.executescript(consumer.SCHEMA_SQL)
        outcome = consumer.consume(connection, built)
        print(f"Now the same session with four failures injected, {len(built)} events:")
        print()
        print(f"  {outcome.applied} applied")
        print(f"  {outcome.ignored_as_duplicate} ignored, the resent window arriving twice")
        print(f"  {outcome.applied_as_correction} applied as a correction of a consumed record")
        assert outcome.suspected_on_arrival is not None
        print(f"  {len(outcome.suspected_on_arrival)} gaps suspected while events were arriving")
        print(f"  {len(outcome.never_arrived)} offsets that never arrived at all")
        print()
        print(f"  The injected gap was {len(injected.gap_offsets)} offsets wide, so one of those")
        print("  suspected gaps was not a gap: it was the out-of-order delivery, resolving when")
        print("  the offset behind it turned up. Alerting on the first number pages somebody")
        print("  for a feed that is working.")
        print()
        again = consumer.consume(connection, built)
        print(f"Replaying the whole tape a second time applies {again.applied} events and")
        print(f"ignores {again.ignored_as_duplicate}. At-least-once delivery makes that ordinary.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
