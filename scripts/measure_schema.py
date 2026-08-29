"""One breaking change to the trade schema, offered under two compatibility settings.

    uv run python scripts/measure_schema.py

WHAT IS MEASURED. A producer adds a required field to the normalised event schema. That is a
breaking change for every consumer already reading it, and whether anybody finds out depends
entirely on one setting nobody looks at:

    BACKWARD   the registry REJECTS it, at registration time, before a single message is
               produced. The producer's own deploy fails, which is where a schema break should
               be discovered.
    NONE       the registry ACCEPTS it. Nothing fails, and every existing consumer is now
               reading messages it cannot decode, one at a time, in production.

BOTH RUNS ARE CAPTURED, because the interesting number is the pair. A registry that rejects
everything is not evidence of anything, and a setting that has never been seen to accept the
same change is not a setting anybody has tested.

THE REGISTRY IS REDPANDA'S, NOT CONFLUENT'S, and that is a deliberate choice recorded in an ADR:
one binary with the registry built in, rather than a broker plus a separate registry service.
Redpanda is BSL 1.1, source-available rather than open source, converting to Apache 2.0 four
years after each release. Confluent Schema Registry was excluded for wanting a second service,
not for its licence.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidence" / "schema"
REGISTRY = os.environ.get("QUEUEZ_REGISTRY", "http://127.0.0.1:18081")
SUBJECT = "normalised-event-value"

CONTENT_TYPE = "application/vnd.schemaregistry.v1+json"

#: The schema every consumer is reading today.
ORIGINAL = {
    "type": "record",
    "name": "NormalisedEvent",
    "fields": [
        {"name": "offset", "type": "long"},
        {"name": "topic", "type": "string"},
        {"name": "domain", "type": "string"},
    ],
}

#: The same schema with a required field added, and no default. A consumer holding the original
#: cannot read a message written with this one, because there is nothing to fall back to.
BREAKING = {
    "type": "record",
    "name": "NormalisedEvent",
    "fields": [
        {"name": "offset", "type": "long"},
        {"name": "topic", "type": "string"},
        {"name": "domain", "type": "string"},
        {"name": "sequence_source", "type": "string"},
    ],
}


def call(method: str, path: str, body: Mapping[str, Any] | None = None) -> tuple[int, str]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{REGISTRY}{path}", data=payload, method=method, headers={"Content-Type": CONTENT_TYPE}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def register(schema: Mapping[str, Any]) -> tuple[int, str]:
    return call("POST", f"/subjects/{SUBJECT}/versions", {"schema": json.dumps(schema)})


def set_compatibility(level: str) -> None:
    status, body = call("PUT", f"/config/{SUBJECT}", {"compatibility": level})
    if status != 200:
        raise SystemExit(f"could not set compatibility to {level}: {status} {body}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    call("DELETE", f"/subjects/{SUBJECT}")
    call("DELETE", f"/subjects/{SUBJECT}?permanent=true")

    results: dict[str, dict[str, Any]] = {}
    for level in ("BACKWARD", "NONE"):
        call("DELETE", f"/subjects/{SUBJECT}")
        call("DELETE", f"/subjects/{SUBJECT}?permanent=true")
        status, body = register(ORIGINAL)
        if status != 200:
            raise SystemExit(f"the original schema was rejected under {level}: {status} {body}")
        set_compatibility(level)
        status, body = register(BREAKING)
        results[level] = {
            "status": status,
            "accepted": status == 200,
            "body": body.strip()[:400],
        }
        print(f"  {level}: HTTP {status}, {'accepted' if status == 200 else 'rejected'}")

    if results["BACKWARD"]["accepted"]:
        print(
            "BACKWARD accepted a required field with no default, so the setting is doing "
            "nothing and this exhibit shows nothing",
            file=sys.stderr,
        )
        return 1
    if not results["NONE"]["accepted"]:
        print(
            "NONE rejected the same change, so the pair does not demonstrate that the setting "
            "is what decides it",
            file=sys.stderr,
        )
        return 1

    (OUT / "summary.json").write_text(
        json.dumps(
            {"subject": SUBJECT, "change": "a required field with no default", "results": results},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with (OUT / "one-change-two-settings.txt").open("w", encoding="utf-8") as handle:
        print("$ uv run python scripts/measure_schema.py", file=handle)
        print(file=handle)
        print(
            "One change: a required field added to the normalised event schema, no default.",
            file=handle,
        )
        print(file=handle)
        for level, result in results.items():
            verdict = "ACCEPTED" if result["accepted"] else "REJECTED"
            print(f"  compatibility {level:<9} HTTP {result['status']}   {verdict}", file=handle)
        print(file=handle)
        print(
            "Under BACKWARD the producer's own registration fails, before a single message is",
            file=handle,
        )
        print(
            "written. Under NONE nothing fails, and every consumer already reading this subject",
            file=handle,
        )
        print(
            "meets a message it cannot decode, one at a time, wherever it happens to be running.",
            file=handle,
        )
        print(file=handle)
        print("The rejection reason, in the registry's own words:", file=handle)
        reason = str(results["BACKWARD"]["body"])[:200]
        print(f"  {reason}", file=handle)

    print((OUT / "one-change-two-settings.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
