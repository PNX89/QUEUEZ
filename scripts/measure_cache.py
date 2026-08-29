"""What a cache does under a stampede, and what its default eviction policy does when it fills.

    uv run --group broker python scripts/measure_cache.py

TWO MEASUREMENTS, both about a cache behaving in a way nobody chose.

    THE STAMPEDE. One hot key expires and every caller misses at the same moment. Without single
    flight, each of them recomputes it: the load the cache exists to prevent arrives all at once,
    and it arrives at the moment the cache is least able to help. With single flight, one caller
    computes and the rest wait for that answer.

    THE DEFAULT POLICY. `maxmemory-policy` defaults to `noeviction`. That is not a cache: when
    memory runs out, writes are REFUSED rather than old keys dropped. A last-value cache
    configured this way stops accepting new quotes at exactly the moment there are more of them
    than usual, and the error surfaces at the writer rather than at the reader, so the first
    symptom is a producer failing for a reason that has nothing to do with the producer.

Both are measured against a real Redis rather than argued about.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidence" / "cache"
URL = os.environ.get("QUEUEZ_REDIS", "redis://127.0.0.1:16379/0")

HOT_KEY = "quote:the-one-everybody-wants"
CALLERS = 24
#: How long the expensive thing takes. Long enough that concurrent callers genuinely overlap.
COMPUTE_SECONDS = 0.25


def main() -> int:
    import redis

    client = redis.Redis.from_url(URL)
    client.ping()
    OUT.mkdir(parents=True, exist_ok=True)

    computed = {"without": 0, "with": 0}
    lock = threading.Lock()

    def expensive() -> bytes:
        time.sleep(COMPUTE_SECONDS)
        return b"1.0842"

    def without_single_flight() -> None:
        if client.get(HOT_KEY) is None:
            value = expensive()
            with lock:
                computed["without"] += 1
            client.set(HOT_KEY, value, ex=60)

    def with_single_flight() -> None:
        if client.get(HOT_KEY) is not None:
            return
        # ONE WINNER, DECIDED BY THE STORE. `set(nx=True)` is atomic, so exactly one caller gets
        # the lease and the rest wait for the value rather than recomputing it. Doing this with
        # a check and then a set would race, which is the bug this is preventing.
        if client.set(f"lease:{HOT_KEY}", b"1", nx=True, ex=30):
            value = expensive()
            with lock:
                computed["with"] += 1
            client.set(HOT_KEY, value, ex=60)
            client.delete(f"lease:{HOT_KEY}")
            return
        for _ in range(200):
            if client.get(HOT_KEY) is not None:
                return
            time.sleep(0.01)

    for name, worker in (("without", without_single_flight), ("with", with_single_flight)):
        client.delete(HOT_KEY, f"lease:{HOT_KEY}")
        threads = [threading.Thread(target=worker) for _ in range(CALLERS)]
        started = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.perf_counter() - started
        print(f"  {name} single flight: {computed[name]} of {CALLERS} recomputed, {elapsed:.2f}s")

    # str() because the client's return type is optional and `config_set` will not take None.
    # A policy that came back missing would be a different problem, and it is checked here
    # rather than allowed to reach the restore in the finally block.
    policy = str(client.config_get("maxmemory-policy")["maxmemory-policy"])
    if not policy:
        print("the server reported no maxmemory-policy at all", file=sys.stderr)
        return 1
    refused = None
    try:
        client.config_set("maxmemory", "2mb")
        client.config_set("maxmemory-policy", "noeviction")
        for index in range(200_000):
            client.set(f"filler:{index}", b"x" * 64)
    except Exception as error:
        refused = type(error).__name__
    finally:
        client.config_set("maxmemory-policy", policy)
        client.config_set("maxmemory", "0")
        client.flushdb()

    if computed["without"] <= computed["with"]:
        print(
            "the stampede did not happen, so single flight is preventing nothing here",
            file=sys.stderr,
        )
        return 1
    if refused is None:
        print(
            "noeviction accepted every write up to the limit, so the exhibit shows nothing",
            file=sys.stderr,
        )
        return 1

    summary = {
        "callers": CALLERS,
        "recomputed_without_single_flight": computed["without"],
        "recomputed_with_single_flight": computed["with"],
        "default_maxmemory_policy": policy,
        "write_refused_under_noeviction": refused,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    with (OUT / "a-cache-that-stops-caching.txt").open("w", encoding="utf-8") as handle:
        print("$ uv run --group broker python scripts/measure_cache.py", file=handle)
        print(file=handle)
        print(f"{CALLERS} callers, one key, expiring at the same moment:", file=handle)
        print(f"  without single flight   {computed['without']} of them recomputed it", file=handle)
        print(f"  with single flight      {computed['with']} of them recomputed it", file=handle)
        print(file=handle)
        print(f"And the eviction policy this server starts with: {policy}.", file=handle)
        print(
            "That is not a cache. When memory runs out it REFUSES writes rather than dropping",
            file=handle,
        )
        print(
            f"old keys, and the write fails with {refused}. A last-value cache configured this",
            file=handle,
        )
        print(
            "way stops accepting quotes at the moment there are more of them than usual, and",
            file=handle,
        )
        print(
            "the error surfaces at the writer, so the first symptom is a producer failing for",
            file=handle,
        )
        print("a reason that has nothing to do with the producer.", file=handle)

    print((OUT / "a-cache-that-stops-caching.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
