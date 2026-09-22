"""The prose is a claim about measured behaviour, so it is tested against the measurement.

`docs/rules/*.md`, `README.md` and `examples/RESULTS.md` are the parts of this repository a
reader trusts most, and none of them is executed by anything else. A rule document that says
`BLOCKING` while the registry says `POTENTIAL`, or a README that quotes output the tool no
longer produces, is worse than no document: it is a confident statement that drifted.

Each check here compares a documented claim with the code or the command that is supposed to
produce it. Where a comparison has to be loose it is loose for a stated reason - the rule
documents describe rules that fire at several severities, so the registry's default must be
*contained* in the document cell rather than equal to it.

Spec TEST 1-37 is the behavioural contract and it is covered elsewhere; nothing here adds a
number to that register. These are documentation-contract tests: they exist because the
documents are the interface a reader trusts before they trust the code.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from dataset_doctor.audit import DETECTORS
from dataset_doctor.rules import REGISTRY, V01_RULES

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
RULE_IDS = sorted(REGISTRY)

WIRED = dict(DETECTORS)


# --------------------------------------------------------------------- document parsing
def _text(rule_id: str) -> str:
    return (ROOT / REGISTRY[rule_id].doc_path).read_text(encoding="utf-8")


def _front_table(rule_id: str) -> dict[str, str]:
    """Rows of the table before the first section heading, keyed by row label."""
    front = _text(rule_id).split("\n## ", 1)[0]
    return {key.strip(): value.strip() for key, value in re.findall(r"^\| ([A-Z][^|]*?) \| (.+?) \|$", front, re.M)}


def _documented_modality(cell: str) -> set[str]:
    """Which dataset types the ``Applies to`` row claims, ignoring cross-references.

    Parenthetical asides and link text name other rules' modalities on purpose - DD012 says
    "tabular (images are DD017)" - so anything inside parentheses or backticks is stripped
    before the words are matched. Without that step the parser certifies a correct document
    as a contradiction, which is the failure mode this file exists to prevent.
    """
    prose = re.sub(r"\[[^]]*\]\([^)]*\)", "", cell)
    prose = re.sub(r"\([^)]*\)", "", prose)
    prose = re.sub(r"`[^`]*`", "", prose)
    return {kind for kind in ("tabular", "image") if re.search(rf"\b{kind}", prose)}


# ------------------------------------------------------------------------- rule documents
@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_a_rule_document_describes_the_registered_rule(rule_id: str) -> None:
    rule = REGISTRY[rule_id]
    rows = _front_table(rule_id)

    assert _text(rule_id).splitlines()[0] == f"# {rule_id} - {rule.name}"
    for label, value in (
        ("Category", rule.category.value),
        ("Default severity", rule.default_severity.value),
        ("Formal impact", rule.formal_impact.value),
        ("Evidence type", rule.evidence_type.value),
    ):
        assert rows, f"{rule_id} has no front table"
        assert f"`{value}`" in rows[label], f"{rule_id}: document says {rows[label]!r}, registry says {value}"


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_a_document_that_restricts_a_rule_to_one_modality_is_honoured(rule_id: str) -> None:
    """``requires`` is the machine-readable half of "applies to"; the prose must not contradict it."""
    required = set(REGISTRY[rule_id].requires)
    expected = {"image"} if "images" in required else {"tabular"} if "tabular" in required else None
    if expected is None:
        pytest.skip("the registry does not bind this rule to a modality, so the document is free")
    cell = _front_table(rule_id)["Applies to"]
    assert _documented_modality(cell) == expected, f"{rule_id}: {cell!r} contradicts requires={sorted(required)}"


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_the_detector_named_in_a_rule_document_is_the_one_that_runs(rule_id: str) -> None:
    """A document can only be a spec if the function it names is the function that executes.

    Line numbers are deliberately not asserted, and deliberately absent from these documents:
    they move every time an unrelated detector is edited, and a stale one is a claim that
    quietly stops being checkable.
    """
    cell = _front_table(rule_id)["Detector"]
    match = re.search(r"([\w/.-]+\.py)::(\w+)", cell)
    assert match, f"{rule_id} names no importable detector: {cell!r}"
    path, name = match.groups()
    assert not re.search(r"\(line \d", cell), f"{rule_id} pins a source line number, which will rot silently"

    function = WIRED[rule_id]
    source = Path(inspect.getsourcefile(function) or "").resolve()
    assert (ROOT / path).resolve() == source, f"{rule_id}: documented {path}, wired to {source.name}"
    assert name == function.__name__, f"{rule_id}: documented {name}, wired to {function.__name__}"


def test_the_rule_documents_and_the_registry_cover_the_same_rules() -> None:
    """Neither a documented rule nobody registered nor a registered rule nobody documented."""
    on_disk = {f"docs/rules/{path.name}" for path in (ROOT / "docs" / "rules").glob("DD*.md")}
    registered = set(REGISTRY)

    assert {path.split("/")[-1].split("-")[0] for path in on_disk} == registered
    for rule_id in RULE_IDS:
        assert (ROOT / REGISTRY[rule_id].doc_path).is_file(), f"{rule_id} points at a missing document"
    assert on_disk == {REGISTRY[rule_id].doc_path for rule_id in RULE_IDS}


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_the_v01_claim_in_a_rule_document_matches_the_v01_rule_set(rule_id: str) -> None:
    """Only some documents carry the row; where one does, it is a checkable claim."""
    cell = _front_table(rule_id).get("In V0.1 rule set")
    if cell is None:
        pytest.skip(f"{rule_id} makes no V0.1 claim")
    says_yes = cell.strip().lower().startswith("yes")
    assert says_yes == (rule_id in V01_RULES), (
        f"{rule_id}: document says {cell!r}, V01_RULES says {rule_id in V01_RULES}"
    )


# --------------------------------------------------------------------------------- README
def test_readme_only_names_rules_that_exist_and_links_to_documents_that_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    named = set(re.findall(r"\bDD\d{3}\b", readme))
    assert named <= set(REGISTRY), f"README names rules the registry does not have: {sorted(named - set(REGISTRY))}"
    assert (ROOT / "docs" / "rules").is_dir() and "docs/rules" in readme, (
        "the rule documents are unreachable from the README"
    )

    for target in re.findall(r"\]\(([^)\s]+\.md)\)", readme):
        if target.startswith(("http://", "https://")):
            continue
        assert (ROOT / target.split("#")[0]).is_file(), f"README links to a missing file: {target}"


def test_readmes_leakage_table_calls_each_rule_the_evidence_type_it_documents() -> None:
    """The README's headline table is the claim most readers act on, and it is one word per row.

    "deterministic" is the word that makes a reader trust a `CRITICAL`, so a row that drifts
    from the rule's own `Evidence type` is the most expensive typo in the repository.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Leakage Detection", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\| (DD\d{3}) \| [^|]* \| ([^|]*) \|$", section, re.M)
    assert rows, "the README no longer carries the leakage table in the shape this test reads"

    for rule_id, claim in rows:
        words = [word for word in ("deterministic", "heuristic") if word in claim.lower()]
        assert len(words) == 1, f"{rule_id}: README row calls its evidence {claim!r}"
        documented = _front_table(rule_id)["Evidence type"].lower()
        assert words[0] in documented, f"{rule_id}: README says {words[0]}, the rule document says {documented}"


# ------------------------------------------------------------------- checked-in measurement
def _build_module() -> object:
    spec = importlib.util.spec_from_file_location("examples_build", EXAMPLES / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not EXAMPLES.is_dir(), reason="example fixtures are not present")
def test_examples_results_md_is_what_the_tool_says_about_the_committed_fixtures(tmp_path: Path) -> None:
    """`examples/RESULTS.md` is generated, so it must still be what the generator produces.

    `build.record()` renders no timestamp and no duration, which is what makes an exact
    comparison possible: any difference is a number that moved, not the clock. The fixtures
    themselves are already covered by `test_examples.py`; this covers the prose that quotes
    their verdicts.
    """
    module = _build_module()
    rendered: str = module.record(EXAMPLES)

    committed = (EXAMPLES / "RESULTS.md").read_text(encoding="utf-8")
    assert rendered == committed, (
        "examples/RESULTS.md no longer matches a live audit of the committed fixtures; "
        "regenerate it with `python examples/build.py --audit`, do not edit it by hand"
    )


# --------------------------------------------------------------------------- README's demo
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BOX = str.maketrans("┌┐└┘├┤─│", "++-+||-|")


def _canonical(text: str) -> list[str]:
    """One normalised line per printed line, with the cosmetics that vary removed.

    Rich draws ASCII or Unicode boxes depending on the terminal and wraps at the terminal
    width, and the header of each box repeats the output path. Those three are the only
    reasons a real run can differ from the same run's README quote, so they are normalised
    away; every character that carries a number or a verdict survives.
    """
    text = _ANSI.sub("", text).replace("\\", "/").translate(_BOX)
    text = re.sub(r"(?<![\w/.])\./?demo-datasets", "<OUT>", text)
    text = re.sub(r"(?<![\w/.])demo-datasets", "<OUT>", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or set(line) <= set("+-| "):
            continue
        lines.append(line.strip("+-| ").strip())
    return [line for line in lines if line]


def _readme_claims(heading: str) -> list[str]:
    """Normalised lines of every measured-output block under one README section."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return [line for block in re.findall(r"```text\n(.*?)```", section, re.S) for line in _canonical(block)]


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = {"PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8", "COLUMNS": "240", "FORCE_COLOR": "0"}
    completed = subprocess.run(
        [sys.executable, "-m", "dataset_doctor.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **environment},
        timeout=600,
    )
    assert completed.returncode == 0, (
        f"`dataset-doctor {' '.join(args)}` exited {completed.returncode}\n{completed.stderr[-2000:]}"
    )
    return completed


def test_readmes_demo_output_is_what_the_demo_command_actually_prints(tmp_path: Path) -> None:
    """The README sells `dataset-doctor demo` with "Real output, verbatim". That is a test."""
    claims = _readme_claims("Demo")
    assert claims, "the README no longer quotes the demo output; this test should be deleted with the claim"

    completed = _run_cli(tmp_path, "demo", "--output", "demo-datasets")
    printed = " ".join(_canonical(completed.stdout))
    missing = [line for line in claims if line not in printed]
    assert not missing, "README quotes output the tool no longer produces:\n" + "\n".join(missing)


def test_readmes_distribution_shift_example_still_measures_that_way(tmp_path: Path) -> None:
    """The README's sharpest claim is a *negative* one, so it needs a guard of its own.

    "`RISKY`, not `INVALID`, and `dataset-doctor audit` exits 0 on it" is the sentence that
    separates this tool from a data-quality score. If DD012 or DD013 ever escalated a pure
    shift into a blocked evaluation, the exit code and the verdict line here would both move
    before the prose looked wrong to a reader.
    """
    claims = _readme_claims("Distribution Shift")
    assert claims, "the README no longer quotes the shift fixture; this test should be deleted with the claim"

    completed = _run_cli(tmp_path, "audit", str(EXAMPLES / "shifted_tabular"))
    printed = " ".join(_canonical(completed.stdout))
    missing = [line for line in claims if line not in printed]
    assert not missing, "README quotes output the tool no longer produces:\n" + "\n".join(missing)
    assert "FORMAL_EVAL_INVALID" not in printed, "a pure distribution shift is not a blocked evaluation"
