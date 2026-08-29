# QUEUEZ

**A feed's sequence is the only ordering a consumer can trust. On a real recorded session the
wall clock steps backwards 547 times while the offset never does, so every rule here asserts on
sequence continuity and none of them looks at a clock.**

[![CI](https://github.com/PNX89/QUEUEZ/actions/workflows/ci.yml/badge.svg)](https://github.com/PNX89/QUEUEZ/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<!-- quoted from docs/evidence/demo.txt -->
```text
  the sequence is monotone with 0 gaps
  the wall clock goes BACKWARDS 547 times, by up to 26 seconds
```

That is 2,025 events from a Wikimedia EventStreams session, recorded once and committed here.
**Source: Wikimedia EventStreams.** A gap detector built on time reports gaps that are not there
and misses the ones that are, which is not a caution but this number.

Each event also carries two clocks, an ISO instant and a Unix second, and they disagree on 1,576
of them. The ISO instant is never the earlier of the two and the gap runs to 27.5 seconds. This
repository does not say why: the feed records what it emitted, not what it was doing.

One file to start with: [`src/queuez/consumer.py`](src/queuez/consumer.py).

## The recorded session is clean, so the failures are injected

No gap and no duplicate in 2,025 events, which is what a healthy feed looks like and why a
consumer tested only against one has been tested against nothing. Four failures go onto an
invented tape at fixed offsets, giving 2,035 events:

<!-- quoted from docs/evidence/demo.txt -->
```text
  2022 applied
  12 ignored, the resent window arriving twice
  1 applied as a correction of a consumed record
  2 gaps suspected while events were arriving
  3 offsets that never arrived at all
```

**Two gap counts, and only one is true.** The injected gap is 3 offsets wide. The second
suspected gap was the out-of-order delivery, which looks exactly like a gap when it arrives and
resolves when the offset behind it turns up. Alerting on the arrival-time count pages somebody
for a feed that is working.

**A correction is not a duplicate**, and to a consumer reading offsets alone they are identical:
both are an offset already seen. One must be dropped and the other applied, so what is recorded
is every distinct content seen for an offset. That also makes a full replay free, which
at-least-once delivery makes ordinary: replaying the whole tape applies nothing.

## The offset lives in the sink, in the same transaction as the write

The broker's own offset store is not the source of truth here. If the process dies between
applying a write and acknowledging it, the broker replays and the sink already knows it applied
that offset. If the offset were committed separately, the same crash loses the write and keeps
the acknowledgement.

That claim is tested by failing the second write and asserting the first was rolled back, which
is the only crash the transaction is actually for. Every other test stopped the consumer between
transactions, and a version with the offset written outside the transaction passed all of them.

The same rules run against SQLite in the offline suite and against PostgreSQL in their own job.
That second job earned its place on its first run: the offsets are around 6.46 billion, which
overflows PostgreSQL's four-byte `integer` and fits SQLite's eight-byte one, so a schema that was
correct in the store this was developed against was wrong in the other.

## One breaking change, two compatibility settings

<!-- quoted from docs/evidence/schema/one-change-two-settings.txt -->
```text
  compatibility BACKWARD  HTTP 409   REJECTED
  compatibility NONE      HTTP 200   ACCEPTED
```

A required field with no default, added to the normalised event schema. Under BACKWARD the
producer's own registration fails before a single message is written. Under NONE nothing fails,
and every consumer already reading the subject meets a message it cannot decode.

The registry is Redpanda's, which serves the **Kafka API** in one binary rather than being Kafka.
Redpanda is BSL 1.1, source-available rather than open source, converting to Apache 2.0 four
years after each release.

## The same normalisation, written twice

A specification with one implementation is a specification nobody has read, so the normalisation
exists again as a standalone Rust binary reading the same committed file, and a conformance suite
compares all 2,027 lines. Neither is the reference: they agree, or the suite fails and says which
line. The decoder has no dependencies, because a CSV crate and a serialisation crate would make
it a demonstration of somebody else's library.

## A cache configured the way it ships

24 callers, one hot key, expiring together: without single flight **24** of them recomputed it,
with it, one. And `maxmemory-policy` ships as `noeviction`, which is not a cache. When memory
runs out it refuses writes rather than dropping old keys, so a last-value cache configured that
way stops accepting quotes at the moment there are more of them than usual, and the error
surfaces at the writer.

## Run it

```text
uv run python examples/the_clock_goes_backwards.py
uv run pytest
```

The legs that need a broker, a database server or another language have their own CI jobs:

```text
uv run python scripts/measure_schema.py
uv run --group broker pytest tests_broker -q
uv run python scripts/measure_conformance.py
uv run --group broker python scripts/measure_cache.py
```

## What is committed, and what was left out

Wikimedia text is CC BY-SA 4.0. The edit comments in these events are people's writing and carry
that licence; the offsets, timestamps, ids and domains are facts about when something happened
and carry none. So the committed file has ten columns and not one of them is a sentence anybody
wrote: the free text is dropped at capture time.

That is the opposite of the decision a sibling makes about a publisher who permits reuse only
WITHOUT modification, where the raw bytes are the only compliant artefact. The constraint runs
the other way here, and the projection is.

**The venues a market data repository would reach for are not available.** Thirteen were checked
and none permits a recorded session in a public repository: six prohibit redistribution, four are
silent while claiming ownership, one requires a paid licence, one forbids automated access, and
the single open exception is AGPL. Silence is not permission. The mechanism is the same whatever
the feed carries, and the subject here is delivery rather than the asset class.

## What this does not do

It does not operate Kafka. It does not reconstruct a book, and nothing here is a matching engine
or an exchange. There is no latency figure anywhere, and no claim that any normalised series was
traded on.

## Development

```text
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy .
```

<!-- toolset:start -->
<!-- toolset:end -->

## Licence

MIT for the code. The recorded session is derived from Wikimedia EventStreams.
