# What is in here, and what was left out

`session_one.csv` is a recorded session from the Wikimedia EventStreams `recentchange` feed,
taken on 29 August 2026. **Source: Wikimedia EventStreams.**

## Why this feed and not a trading venue

A repository about at-least-once delivery needs a push surface with real sequence semantics, and
market data venues do not permit a recorded session to be redistributed. Thirteen were checked
before this one was chosen: six prohibit redistribution in their terms, four are silent while
carrying a general ownership clause, one requires a paid data licence, one requires an account
and forbids automated access, and the one genuinely open exception is AGPL-3.0, which does not
sit in an MIT repository. Silence is not permission.

## What was kept, and why the rest was dropped

Wikimedia text is CC BY-SA 4.0. The edit comments in these events are people's writing and carry
that licence with them. The offsets, timestamps, ids and domains are facts about when something
happened, and no licence covers those.

So this file has ten columns and none of them is a sentence anybody wrote. `comment`,
`parsedcomment`, `title` and `user` are all dropped at capture time in
`scripts/capture_stream.py`, which is the only place they are ever seen.

**That is the opposite decision from the one a sibling repository makes about the ECB**, and the
reason is the licence rather than a preference. Where a publisher permits reuse only WITHOUT
modification, the raw bytes are the only compliant artefact and a tidied file would breach it.
Here the constraint runs the other way: keeping the free text would pull a share-alike licence
into an MIT repository, so the projection is the compliant artefact and the raw body is not.

## What the session contains

2,027 events across two topics, which are two datacentres. The offsets are monotone within each
topic and the two topics run in entirely different ranges, so they are two sequences rather than
one. There is no gap and no duplicate anywhere in it, which is what a healthy feed looks like
and why `src/queuez/tape.py` invents the failures rather than waiting for them.
