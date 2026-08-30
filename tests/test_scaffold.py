"""The checks that exist because a sibling repository shipped without them.

Each one here is a defect that reached main somewhere else in this toolset and was found late.
They are cheap, they run before any of this repository's own subject matter exists, and they are
written first for that reason.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[1]

#: What the broker leg installs, as IMPORT names, pinned here by name and by size. Two tests
#: below read it, so a tuple that quietly lost an entry would leave both of them covering one
#: package fewer and still green. It is checked against the dependency group it describes.
MEASURED_WITH = ("psycopg", "redis")


def pyproject() -> dict[str, object]:
    loaded: dict[str, object] = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))
    return loaded


def test_the_package_imports_and_declares_a_version() -> None:
    """The cheapest possible check that the wheel layout is right."""
    import queuez

    assert queuez.__version__
    project = pyproject()["project"]
    assert isinstance(project, dict)
    assert queuez.__version__ == project["version"], (
        "the package and pyproject state different versions, so the release tag would name one "
        "of them and the installed artefact the other"
    )


def test_every_declared_marker_is_carried_by_a_test() -> None:
    """A marker naming a rig that does not exist reads as coverage.

    A sibling declared three markers, two of which matched no test anywhere, and they were
    deselected by default so nothing ever ran them or reported their absence. The test guarding
    the list compared the three NAMES against pyproject, which is a check that the file agrees
    with itself.
    """
    tool = pyproject().get("tool", {})
    assert isinstance(tool, dict)
    pytest_config = tool.get("pytest", {})
    assert isinstance(pytest_config, dict)
    options = pytest_config.get("ini_options", {})
    assert isinstance(options, dict)
    declared = options.get("markers", [])
    assert isinstance(declared, list)

    body = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((REPO / "tests").glob("test_*.py"))
    )
    for marker in declared:
        name = str(marker).split(":")[0].strip()
        assert f"@pytest.mark.{name}" in body, (
            f"marker {name!r} is declared and no test carries it, so it describes a rig that "
            f"does not exist"
        )


def test_mypy_covers_every_directory_holding_python() -> None:
    """The list grows with the first file in a directory, and this is what fires on that commit.

    In a sibling, `scripts` was outside the mypy list, so the two scripts CI depended on were
    the only Python in the tree that nothing type checked. The list cannot simply be written in
    advance instead, because naming a directory mypy cannot find is an error rather than a no-op.
    """
    tool = pyproject()["tool"]
    assert isinstance(tool, dict)
    mypy = tool["mypy"]
    assert isinstance(mypy, dict)
    files = mypy["files"]
    assert isinstance(files, list)
    checked = {str(entry) for entry in files}

    holding = {
        path.relative_to(REPO).parts[0]
        for path in REPO.rglob("*.py")
        if ".venv" not in path.parts
        and "__pycache__" not in path.parts
        and len(path.relative_to(REPO).parts) > 1
    }
    missing = holding - checked
    assert missing == set(), f"these directories hold Python and mypy does not read them: {missing}"


def test_the_suite_that_needs_a_broker_is_run_by_ci() -> None:
    """The other half of splitting the suite, and the half that is easy to forget.

    Moving the tests that need a PostgreSQL server and psycopg out of `testpaths` makes the
    offline claim true and makes those tests trivially skippable: they are now in a directory
    nothing runs unless something says so. So the workflow is parsed and the command that runs
    them is asserted, rather than the directory merely existing.
    """
    import yaml

    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    executed = "\n".join(
        line
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
        for line in step["run"].splitlines()
        if not line.strip().startswith("#")
    )
    if not (REPO / "tests_broker").is_dir():
        return  # The broker leg has not arrived yet, and a test for it would be a claim.
    collected = sorted(path.name for path in (REPO / "tests_broker").glob("test_*.py"))
    assert collected, "tests_broker is empty, so the split bought nothing"
    assert "pytest tests_broker" in executed, (
        f"CI never runs tests_broker, so {collected} are collected by nobody and the split "
        f"turned a slow suite into an unrun one"
    )


def test_no_third_party_binary_is_tracked() -> None:
    """A vendored engine binary in git history is a hundred megabytes nobody can remove later.

    ASKS GIT, AND THE FIRST VERSION WALKED THE WORKING TREE. It said "tracked" in its name and
    scanned every file on disk, so any virtualenv holding an executable with one of these names
    turned it red: a virtualenv is not the repository, and a test that cannot tell the
    difference reports a defect that does not exist while proving nothing about what was
    committed.

    The three names are the servers this repository actually talks to. A list naming engines it
    has never heard of would look like coverage and watch nothing.
    """
    import subprocess

    listed = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO, check=True
    ).stdout.split()
    names = {pathlib.PurePosixPath(entry).name for entry in listed}
    for binary in ("redpanda", "rpk", "redis-server", "postgres"):
        assert binary not in names, f"a {binary} binary is committed"

    big = [
        entry
        for entry in listed
        if (REPO / entry).exists() and (REPO / entry).stat().st_size > 5_000_000
    ]
    assert big == [], f"these committed files are over five megabytes: {big}"


def test_the_offline_suite_imports_nothing_from_the_verdict_or_contract_groups() -> None:
    """The claim that cloning this and running pytest with `--dev` alone works.

    psycopg and redis are what the broker legs are MEASURED WITH: a PostgreSQL server on the
    other end of a socket, and a Redis the cache measurements fill up. They are named in their
    own dependency group so that the boundary is visible in one file. The boundary only means
    anything if the offline suite really does stay on the other side of it, so it is asserted
    rather than intended, from the first commit rather than after somebody notices.
    """
    # pytest and ruff are deliberately NOT in this list. They ship in the dev group, they are
    # how the suite is run rather than what any measurement is taken with, and the line the
    # dependency groups draw is exactly that one.
    offenders: list[str] = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            for package in MEASURED_WITH:
                if stripped.startswith((f"import {package}", f"from {package}")):
                    offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], (
        f"the offline suite imports a measuring instrument, so it is no longer the thing a "
        f"stranger gets by cloning and running pytest: {offenders}"
    )


def test_the_ban_list_is_the_broker_group_and_its_docstring_names_the_same_packages() -> None:
    """A DOCSTRING EXPLAINING A DIFFERENT LIST CAME FROM A DIFFERENT REPOSITORY.

    The test above bans exactly what the broker leg installs, and its docstring is where a
    reader learns why that boundary is drawn. That docstring named four tools this repository
    has never depended on while the list beside it held three others, and nothing noticed,
    because a docstring is not executed and a reader who spots the mismatch has already decided
    what the test directory is worth.

    Both halves are asserted: that the banned list is the dependency group it claims to be, so a
    package added to the group cannot be imported into the offline suite unnoticed, and that the
    prose beside it names those same packages.
    """
    groups = pyproject()["dependency-groups"]
    assert isinstance(groups, dict)
    assert MEASURED_WITH, "nothing is banned from the offline suite, so the boundary is not drawn"

    declared = tuple(
        sorted(
            re.split(r"[<>=\[;]", entry)[0].strip().replace("-", "_") for entry in groups["broker"]
        )
    )
    assert declared == tuple(sorted(MEASURED_WITH)), (
        f"the broker group installs {declared} and the offline suite bans {MEASURED_WITH}. One "
        f"of them can now be imported into the suite a stranger gets by cloning and running "
        f"pytest, or the ban names a package nothing installs"
    )

    explanation = test_the_offline_suite_imports_nothing_from_the_verdict_or_contract_groups.__doc__
    assert explanation
    unnamed = [package for package in MEASURED_WITH if package not in explanation]
    assert unnamed == [], (
        f"the docstring explaining the ban list never mentions {unnamed}, so it is describing "
        f"some other repository's dependencies to a reader of this one"
    )


def test_every_untyped_third_party_module_is_named_at_both_levels() -> None:
    """The condition CI runs in, asserted rather than reasoned about.

    The lint job installs `--dev` and nothing else, so the broker and store packages do not
    exist on the runner. That produces `import-not-found`, a different error from the
    `attr-defined` seen where a package is installed but ships no types, and an override naming
    only a submodule silences one of the two.
    """
    overrides = pyproject()["tool"]["mypy"]["overrides"]  # type: ignore[index]
    named: set[str] = set()
    for override in overrides:
        named.update(override.get("module", []))

    imported: set[str] = set()
    for directory in ("src", "scripts", "tests", "tests_broker", "examples"):
        for path in (REPO / directory).rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                for package in MEASURED_WITH:
                    if stripped.startswith((f"import {package}", f"from {package}")):
                        imported.add(package)

    for package in sorted(imported):
        assert package in named, (
            f"{package} is imported and not named as untyped, so mypy will fail to find it on a "
            f"runner that installed the dev group alone"
        )
        assert f"{package}.*" in named, f"{package}.* is not named, so a submodule import fails"
