"""Record a session from a real public push feed, and keep only what is not somebody's writing.

    uv run python scripts/capture_stream.py --seconds 90

WHY THIS FEED. A repository about at-least-once delivery needs a push surface with real
sequence semantics, and market data venues do not permit redistribution: thirteen were checked
and not one allows a recorded session to be committed to a public repository. Wikimedia
EventStreams does, it is keyless, and it carries the properties that matter:

    a monotone per-partition OFFSET in every event's own metadata
    two datacentres in one stream, so a consumer sees more than one origin
    two clock conventions in one payload, an ISO instant and a Unix second
    resume from an offset, which is what makes an at-least-once story real rather than modelled

WHAT IS DROPPED, AND WHY IT IS DROPPED RATHER THAN KEPT. Wikimedia text is CC BY-SA 4.0. The
edit comments in these events are people's writing and carry that licence with them; the
offsets, timestamps, ids and domains are facts about when something happened, which no licence
covers. An MIT repository that committed the comments would be quietly mixing licences, so this
keeps the facts and drops every free-text field. The source is attributed anyway, because
attribution costs nothing and is the right thing to do.

THAT IS THE OPPOSITE DECISION FROM A SIBLING'S and the reason is the licence, not a preference.
Where a publisher permits reuse only WITHOUT modification, the raw bytes are the only compliant
artefact. Here the constraint runs the other way.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "queuez" / "data"

STREAM = "https://stream.wikimedia.org/v2/stream/recentchange"

#: The fields kept, and every one of them is a fact rather than a sentence somebody wrote.
FIELDS = (
    "offset",
    "partition",
    "topic",
    "event_id",
    "domain",
    "kind",
    "iso_instant",
    "unix_second",
    "revision_old",
    "revision_new",
)


def parse(block: str) -> dict[str, object] | None:
    """One SSE event into one row, or None if it is not a message."""
    payload = None
    for line in block.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
    if payload is None:
        return None
    meta = payload.get("meta", {})
    if "offset" not in meta:
        return None
    revision = payload.get("revision") or {}
    return {
        "offset": meta["offset"],
        "partition": meta.get("partition"),
        "topic": meta.get("topic"),
        "event_id": meta.get("id"),
        "domain": meta.get("domain"),
        "kind": payload.get("type"),
        "iso_instant": meta.get("dt"),
        "unix_second": payload.get("timestamp"),
        "revision_old": revision.get("old"),
        "revision_new": revision.get("new"),
    }


def record(seconds: int) -> list[dict[str, object]]:
    request = urllib.request.Request(STREAM, headers={"User-Agent": "queuez-capture"})
    started = datetime.datetime.now(tz=datetime.UTC)
    rows: list[dict[str, object]] = []
    block: list[str] = []
    with urllib.request.urlopen(request, timeout=seconds + 30) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if line:
                block.append(line)
                continue
            row = parse("\n".join(block))
            block = []
            if row is not None:
                rows.append(row)
            if (datetime.datetime.now(tz=datetime.UTC) - started).total_seconds() >= seconds:
                break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--name", default="session")
    arguments = parser.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    rows = record(arguments.seconds)
    if len(rows) < 100:
        print(f"only {len(rows)} events arrived, which is too few to say anything", file=sys.stderr)
        return 1

    path = DATA / f"{arguments.name}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {path.relative_to(ROOT)}: {len(rows)} events")
    print(f"  topics: {sorted({str(row['topic']) for row in rows})}")
    print(f"  domains: {len({row['domain'] for row in rows})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
