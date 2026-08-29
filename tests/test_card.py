"""The facts the portfolio card states, checked against the repository rather than the file.

`docs/evidence/facts.json` is the one captured artefact CI does not compare byte for byte,
because it carries a capture date and a byte comparison of a date fails on the second morning.
That exemption is only defensible if its contents are checked another way.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tomllib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
FACTS = REPO / "docs" / "evidence" / "facts.json"


def facts() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FACTS.read_text(encoding="utf-8"))
    return loaded


def test_the_stated_test_total_counts_both_suites() -> None:
    """A total counting only `tests` would miss every test that needs a real PostgreSQL.

    The suites are split so that cloning and running pytest works with the dev group alone. That
    is an implementation detail of the rig, not of the repository, so the number a reader is
    shown covers both.
    """
    total = 0
    for directory in ("tests", "tests_broker"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", directory],
            capture_output=True,
            text=True,
            cwd=REPO,
            check=True,
        )
        total += sum(
            int(count) for _, count in re.findall(r"^(\S+): (\d+)$", result.stdout, re.MULTILINE)
        )
    assert total > 0
    assert facts()["tests"] == total, (
        f"the card states {facts()['tests']} tests and the two suites collect {total}. Re-run "
        f"scripts/capture_evidence.py"
    )


def test_the_stated_python_range_is_the_one_ci_runs() -> None:
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    versions = re.findall(r'"(\d+\.\d+)"', workflow)
    assert versions
    assert facts()["python"] == f"{min(versions, key=float)} to {max(versions, key=float)}"


def test_the_stated_release_matches_the_package_version() -> None:
    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert facts()["release"].startswith(f"v{version}")


def test_the_capture_date_is_not_in_the_future() -> None:
    """Bounded rather than matched, because checking it against today fails tomorrow."""
    import datetime

    assert datetime.date.fromisoformat(facts()["captured"]) <= datetime.date.today()


def test_a_published_card_shows_the_captured_demo_and_no_banned_dash() -> None:
    """Only once one exists. A card is written at publication."""
    card = REPO / "site" / "index.html"
    if not card.exists():
        return
    html = card.read_text(encoding="utf-8")
    demo = (REPO / "docs" / "evidence" / "demo.txt").read_text(encoding="utf-8")
    first = next(line for line in demo.splitlines() if line.strip())
    assert first in html, "the card was not generated from the committed capture"
    # ESCAPES RATHER THAN THE CHARACTERS, and the first draft of this line used the characters
    # in the comment directly under a comment saying not to. The linter caught it.
    for dash in ("\u2014", "\u2013"):
        assert dash not in html, f"the published card contains {dash!r}"
