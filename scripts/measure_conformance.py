"""Two implementations of one normalisation, compared line by line, and timed.

    uv run python scripts/measure_conformance.py

NEITHER IS THE REFERENCE, and that is the whole design of this. Both read the same committed
file and write the same normalised series; if they disagree anywhere, the suite fails and says
where. It does not pick a winner, because there is no reason to think the older one is right.

THE TIMING IS REPORTED AND IS NOT THE POINT. It is one file, read once, on whatever machine
happened to run it, and it is published because the question gets asked rather than because it
decides anything. No throughput figure here is representative of anything.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from queuez import session  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "conformance"
BINARY = ROOT / "decoder" / "target" / "release" / "queuez-decoder"
SESSION = ROOT / "src" / "queuez" / "data" / "session_one.csv"


def main() -> int:
    if not BINARY.exists():
        print(
            f"{BINARY.relative_to(ROOT)} is not built. Run cargo build --release in decoder/",
            file=sys.stderr,
        )
        return 1

    OUT.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    from_python = session.normalised(session.read("session_one"))
    python_seconds = time.perf_counter() - started

    started = time.perf_counter()
    try:
        result = subprocess.run(
            [str(BINARY), str(SESSION)], capture_output=True, text=True, check=True
        )
    except OSError as error:
        # A CLEAR MESSAGE RATHER THAN A TRACEBACK, because this happens for an ordinary reason.
        # The binary is built for whatever platform built it. Building it in a Linux container
        # on a Mac produces an ELF the host cannot execute, and the OSError for that reads as a
        # bug in this script. CI builds and runs it natively, where the question does not arise.
        print(
            f"the decoder at {BINARY.relative_to(ROOT)} cannot be executed here: {error}.\n"
            f"It was built for a different platform. Build it natively with "
            f"`cargo build --release` in decoder/, or run this in CI where both are native.",
            file=sys.stderr,
        )
        return 1
    rust_seconds = time.perf_counter() - started
    from_rust = result.stdout.splitlines()

    if len(from_python) != len(from_rust):
        print(
            f"the two implementations produced {len(from_python)} and {len(from_rust)} lines",
            file=sys.stderr,
        )
        return 1

    disagreements = [
        {"line": number, "python": a, "rust": b}
        for number, (a, b) in enumerate(zip(from_python, from_rust, strict=True), 1)
        if a != b
    ]
    if disagreements:
        print(
            f"{len(disagreements)} lines differ, the first at {disagreements[0]}", file=sys.stderr
        )
        (OUT / "disagreements.json").write_text(
            json.dumps(disagreements[:50], indent=2) + "\n", encoding="utf-8"
        )
        return 1

    summary = {
        "events": len(from_python),
        "identical": True,
        "python_seconds": round(python_seconds, 4),
        "rust_seconds": round(rust_seconds, 4),
        "note": (
            "One file, read once, on one machine. Published because the question is asked, not "
            "because it decides anything, and representative of nothing."
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    with (OUT / "two-implementations.txt").open("w", encoding="utf-8") as handle:
        print("$ uv run python scripts/measure_conformance.py", file=handle)
        print(file=handle)
        print(f"{len(from_python)} events, normalised twice, compared line by line.", file=handle)
        print("  identical: yes", file=handle)
        print(file=handle)
        print(
            "Neither implementation is the reference. They agree, or this fails and says",
            file=handle,
        )
        print(
            "which line. The timing below is one file on one machine and is representative",
            file=handle,
        )
        print("of nothing at all.", file=handle)
        print(file=handle)
        print(f"  python  {python_seconds:.4f}s", file=handle)
        print(f"  rust    {rust_seconds:.4f}s   (including process start)", file=handle)

    print((OUT / "two-implementations.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
