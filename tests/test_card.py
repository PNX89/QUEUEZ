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

import pytest
import yaml

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
    """The range read as structure, not as any quoted decimal the workflow happens to contain.

    THIS USED TO MATCH `re.findall(r'"(\\d+\\.\\d+)"', workflow)` OVER THE WHOLE FILE AND ORDER
    THE RESULT WITH `float`, a verbatim copy of the same broken expression `python_range` used to
    compute the number in the first place. Once the two sides ran identical code the assertion
    could not disagree with itself, and the regex over the whole file would also have picked up
    any other quoted `x.y`, an action version or an image tag, that a future workflow edit adds.
    This reads only the `python-versions` matrix each gating job declares and orders it as
    versions, so it fails if the published range stops being that matrix's low and high end.
    """
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    versions: set[str] = set()
    for job in (workflow.get("jobs") or {}).values():
        if job.get("continue-on-error"):
            continue
        declared = (job.get("with") or {}).get("python-versions")
        if declared is None:
            continue
        parsed = json.loads(declared) if isinstance(declared, str) else declared
        versions.update(str(v) for v in parsed)
    assert versions, "no gating job declares python-versions, so the card verifies nothing"
    ordered = sorted(versions, key=lambda v: tuple(int(part) for part in v.split(".")))
    assert facts()["python"] == f"{ordered[0]} to {ordered[-1]}"


def test_the_stated_release_matches_the_package_version() -> None:
    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert facts()["release"].startswith(f"v{version}")


def test_the_capture_date_is_not_in_the_future() -> None:
    """Bounded rather than matched, because checking it against today fails tomorrow."""
    import datetime

    assert datetime.date.fromisoformat(facts()["captured"]) <= datetime.date.today()


def card_check() -> Any:
    """scripts/check_card.py, which the publication gate runs as well."""
    sys.path.insert(0, str(REPO / "scripts"))
    import check_card

    return check_card


def test_a_published_card_shows_the_captured_demo_and_no_banned_dash() -> None:
    """THE PAGE THE ARGUMENT IS READ FROM, COMPARED AGAINST THE REPOSITORY IT DESCRIBES.

    Only once one exists. A card is written at publication.

    THIS COMPARED THE FIRST LINE OF THE TRANSCRIPT AND NOTHING ELSE, and so did the publication
    gate. The other twenty-nine lines of the terminal block, the claim paragraph carrying 547 and
    26 seconds, and the test count in the facts strip were compared against nothing, while the
    card's own note told the reader that a test fails when the page stops matching a live run. A
    card claiming three backwards steps out of eleven and four thousand tests passed every test
    in this file and would have deployed.
    """
    card = REPO / "site" / "index.html"
    if not card.exists():
        return
    html = card.read_text(encoding="utf-8")
    check_card = card_check()
    found = check_card.problems(
        html,
        (REPO / "docs" / "evidence" / "demo.txt").read_text(encoding="utf-8"),
        facts(),
        check_card.measured_figures(),
    )
    assert found == [], "the published card does not match this repository:\n" + "\n".join(found)
    # ESCAPES RATHER THAN THE CHARACTERS, and the first draft of this line used the characters
    # in the comment directly under a comment saying not to. The linter caught it.
    for dash in ("\u2014", "\u2013"):
        assert dash not in html, f"the published card contains {dash!r}"


def test_the_card_check_reports_a_card_that_is_wrong_on_purpose() -> None:
    """THE GUARD ABOVE, POINTED AT PAGES THAT ARE FALSE, because it passes either way otherwise.

    A comparison that has stopped comparing produces exactly what a page that matches produces,
    which is how the one-line version survived. So four cards are built here, each false in one
    of the four ways the real one can be false, and the check has to say so about every one.
    """
    check_card = card_check()
    demo = "2025 events\n\n  the sequence is monotone with 0 gaps\n"
    captured = {"tests": 71, "python": "3.11 to 3.13", "release": "v0.1.0"}
    figures = {2024, 2025, 547, 26, 13}
    honest = (
        '<pre tabindex="0">2025 events\n\n  the sequence is monotone with 0 gaps</pre>'
        "<dl><div><dt>Tests</dt><dd>71</dd></div>"
        "<div><dt>Python</dt><dd>3.11 to 3.13</dd></div>"
        "<div><dt>Release</dt><dd>v0.1.0</dd></div></dl>"
        '<p class="claim">The wall clock steps backwards 547 times out of 2,024.</p>'
    )
    assert check_card.problems(honest, demo, captured, figures) == [], (
        "the check reports a card that states nothing but what was measured"
    )

    for doctored, wrong in (
        (honest.replace("547", "3"), "a backwards count nothing measures"),
        (
            honest.replace("<dd>71</dd>", "<dd>4000</dd>"),
            "a test total that is not the captured one",
        ),
        (honest.replace("monotone with 0", "monotone with 9"), "a transcript line that was edited"),
        (honest.replace('<p class="claim">', "<p>"), "no claim sentence at all"),
    ):
        assert check_card.problems(doctored, demo, captured, figures), (
            f"the check passed a card carrying {wrong}"
        )


def test_the_python_range_is_the_gating_matrix_and_orders_as_versions(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two latent defects in the function that publishes this number, neither of them visible.

    The range on the card is correct today. It was produced by a function that matched every
    quoted `x.y` anywhere in the workflow, so a quoted action version or a timeout would have
    landed on a published page, and that ordered with `float`, so `float("3.9") > float("3.13")`
    and a 3.9 leg would have published a range running backwards.

    A correct output from a broken mechanism is the thing this whole portfolio argues against, so
    the mechanism is tested rather than the output.
    """
    import json as _json
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import capture_evidence

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    gating: set[str] = set()
    for job in (workflow.get("jobs") or {}).values():
        if job.get("continue-on-error"):
            continue
        declared = (job.get("with") or {}).get("python-versions")
        if declared is None:
            continue
        gating.update(
            str(v) for v in (_json.loads(declared) if isinstance(declared, str) else declared)
        )

    assert gating, "no job gates on a Python version, so the published range verifies nothing"
    order = sorted(gating, key=lambda v: tuple(int(p) for p in v.split(".")))
    expected = f"{order[0]} to {order[-1]}"

    assert capture_evidence.python_range() == expected
    facts = _json.loads((REPO / "docs" / "evidence" / "facts.json").read_text("utf-8"))
    assert facts["python"] == expected, (
        f"the card says {facts['python']} and CI gates on {expected}"
    )

    # THE ORDERING RULE, DRIVEN THROUGH THE REAL FUNCTION rather than restated beside it.
    #
    # This matters because of how the defect hides. No matrix in this repository contains a 3.9,
    # so float ordering and version ordering agree on every version actually present, and
    # swapping the production line back to `key=float` changes no output and fails nothing. A
    # test that only asserted the rule as arithmetic would pin a fact and let the code revert.
    #
    # So the function is pointed at a workflow that DOES contain a 3.9, by moving its ROOT, and
    # asked what it returns. Under `key=float` that is "3.11 to 3.9", a range running backwards
    # on a published page.
    fake = tmp_path / ".github" / "workflows"
    fake.mkdir(parents=True)
    (fake / "ci.yml").write_text(
        'jobs:\n  checks:\n    with:\n      python-versions: \'["3.11", "3.9", "3.13"]\'\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(capture_evidence, "ROOT", tmp_path)
    assert capture_evidence.python_range() == "3.9 to 3.13", (
        "the version range is not ordered as versions. float('3.9') is greater than "
        "float('3.13'), so this publishes a range running backwards the day a 3.9 leg exists"
    )
