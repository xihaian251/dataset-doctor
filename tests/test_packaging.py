"""The packaging contract a clone depends on.

`dataset_doctor/reports/` was silently absent from the first commit because an unanchored
`reports/` line in `.gitignore` matched the source package as well as the output directory,
and `cli.py` imports it. Nothing in the test suite noticed, because the tests run against a
working tree rather than against what a clone would receive. These checks close that hole:
they ask git, not the filesystem, what the repository actually contains.
"""

from __future__ import annotations

import importlib
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "dataset_doctor"


def _pyproject() -> dict:
    with (REPO / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _running_under_git() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


pytestmark = pytest.mark.skipif(not _running_under_git(), reason="the source tree is not a git work tree")


def _source_modules() -> list[str]:
    return sorted(
        path.relative_to(REPO).as_posix() for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_every_source_module_of_the_package_is_visible_to_git() -> None:
    """A module git cannot see is a module no clone, sdist or wheel will ever contain."""
    tracked = set(_git("ls-files").stdout.splitlines())
    missing = [module for module in _source_modules() if module not in tracked]

    assert missing == []
    # The regression this test exists for: the report writers are imports, not artefacts.
    assert "dataset_doctor/reports/__init__.py" in tracked
    assert {
        "dataset_doctor/reports/html.py",
        "dataset_doctor/reports/markdown.py",
        "dataset_doctor/reports/repair.py",
    } <= tracked


def test_no_source_module_is_git_ignored() -> None:
    """`--check-ignore` answers the question `.gitignore` patterns actually pose."""
    probe = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "--stdin"],
        input="\n".join(_source_modules()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    ignored = [line for line in probe.stdout.splitlines() if line]

    assert ignored == []


def test_the_console_script_target_resolves() -> None:
    """`[project.scripts]` is a claim about importable objects, so test the claim."""
    entry = _pyproject()["project"]["scripts"]["dataset-doctor"]
    module_name, _, attribute = entry.partition(":")

    imported = importlib.import_module(module_name)

    assert callable(getattr(imported, attribute, None)), f"{entry} is not a callable target"


def test_the_build_targets_cover_the_files_a_distributor_needs() -> None:
    """A missing licence in the sdist is a licence problem, not a cosmetic one.

    Read from the build configuration rather than a built artefact, so the check runs
    without a network or an installed build backend.
    """
    targets = _pyproject()["tool"]["hatch"]["build"]["targets"]

    assert targets["wheel"]["packages"] == ["dataset_doctor"]
    sdist = set(targets["sdist"]["include"])
    missing = {"dataset_doctor", "docs", "examples", "tests", "README.md", "CHANGELOG.md", "LICENSE"} - sdist

    assert missing == set(), f"{sorted(missing)} would be absent from the sdist"
