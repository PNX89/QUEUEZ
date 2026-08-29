"""An invented tape, built from a recorded session, carrying the four failures on purpose.

WHY INVENT ANYTHING when a real session is committed beside it. Because the real one is CLEAN:
2,025 events on the busy topic with no gap and no duplicate. That is what a healthy feed looks
like, and a consumer tested only against it has been tested against nothing it is for. The
failures have to be injected, at known offsets, so that what the consumer does about them is a
fact rather than a hope.

THE FOUR, and each is a different thing that a real feed does.

    A SEQUENCE GAP          offsets simply missing. Either the producer skipped them or the
                            consumer never received them, and from here those are the same
                            event: something that should have arrived did not.
    OUT OF ORDER            two events delivered in the wrong order. The sequence still contains
                            both, so this is recoverable, and a consumer that assumed arrival
                            order was sequence order gets it wrong.
    A DISCONNECT AND RESEND the feed drops and the producer replays a window on reconnect. Every
                            event in that window arrives twice. This is what at-least-once
                            delivery MEANS, and a consumer that adds them twice reports double
                            the volume.
    A CORRECTION            an event arrives for an offset already consumed, carrying different
                            content. Not a duplicate: a restatement. A consumer that dedupes on
                            the offset alone silently discards it.

THE LAST TWO LOOK IDENTICAL TO A CONSUMER THAT ONLY READS OFFSETS, which is the whole difficulty:
one must be dropped and the other must be applied, and telling them apart needs more than the
sequence number.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .session import Event

#: Where each failure is injected, as an index into the source session. Fixed rather than random
#: so that the tape is the same on every machine and the tests can name what they expect.
GAP_AT = 200
GAP_LENGTH = 3
SWAP_AT = 400
RESEND_FROM = 600
RESEND_LENGTH = 12
CORRECTION_AT = 900


@dataclass(frozen=True)
class Injected:
    """What was done to the tape, so a test can assert against it rather than against a memory."""

    gap_offsets: tuple[int, ...]
    swapped_offsets: tuple[int, int]
    resent_offsets: tuple[int, ...]
    corrected_offset: int


def build(events: list[Event]) -> tuple[list[Event], Injected]:
    """The tape, and the record of what was done to it."""
    ordered = sorted(events, key=lambda event: event.offset)
    if len(ordered) < CORRECTION_AT + 10:
        raise ValueError(f"{len(ordered)} events is too short to inject at {CORRECTION_AT}")

    gap = tuple(event.offset for event in ordered[GAP_AT : GAP_AT + GAP_LENGTH])
    kept = [event for event in ordered if event.offset not in gap]

    tape = list(kept)
    swapped = (tape[SWAP_AT].offset, tape[SWAP_AT + 1].offset)
    tape[SWAP_AT], tape[SWAP_AT + 1] = tape[SWAP_AT + 1], tape[SWAP_AT]

    window = tape[RESEND_FROM : RESEND_FROM + RESEND_LENGTH]
    resent = tuple(event.offset for event in window)
    tape = tape[: RESEND_FROM + RESEND_LENGTH] + list(window) + tape[RESEND_FROM + RESEND_LENGTH :]

    original = tape[CORRECTION_AT]
    # A CORRECTION IS THE SAME OFFSET WITH DIFFERENT CONTENT, which is what makes it not a
    # duplicate. The domain is changed because it is the field the consumer folds on.
    correction = replace(original, domain=f"corrected.{original.domain}")
    tape = [*tape[: CORRECTION_AT + 1], correction, *tape[CORRECTION_AT + 1 :]]

    return tape, Injected(
        gap_offsets=gap,
        swapped_offsets=swapped,
        resent_offsets=resent,
        corrected_offset=original.offset,
    )
