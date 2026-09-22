"""The report contract: what a parser, a CI job and a human reviewer each read.

JSON is authoritative - Markdown and HTML are renderings and may not invent anything. The
exit codes are the other half of the contract, because they are the only part a pipeline
sees: 0 nothing blocking, 1 a formal evaluation would not be trustworthy, 2 the tool was
asked something it cannot answer, 3 the tool itself failed.

Spec test coverage: TEST 33 (schema stability), TEST 34 (exit codes), TEST 21 (interrupted
run leaves no damaged report).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import TABULAR_CONFIG, row, write_rows

import dataset_doctor.cli as cli_module
from dataset_doctor import audit_dataset
from dataset_doctor.cli import main
from dataset_doctor.models import SCHEMA_VERSION, AuditReport, Severity
from dataset_doctor.reports import write_reports

COLUMNS = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target"]

# The field set spec section 5 freezes. A missing field breaks every consumer; an added one
# is fine, so this is asserted as a subset check rather than equality.
FINDING_FIELDS = {
    "finding_id",
    "rule_id",
    "title",
    "category",
    "severity",
    "confidence",
    "status",
    "evidence_type",
    "formal_impact",
    "description",
    "why_it_matters",
    "affected_samples",
    "affected_count",
    "evidence",
    "recommended_action",
    "auto_fix_available",
    "location",
    "limitations",
}
REPORT_FIELDS = {
    "schema_version",
    "tool_version",
    "generated_at",
    "identity",
    "eval_safety",
    "eval_safety_reasons",
    "summary",
    "rule_outcomes",
    "findings",
    "methodology",
    "limitations",
    "coverage",
}


def _dataset(root: Path, leaky: bool) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)
    if leaky:
        # The same eight rows again on the other side of the split boundary: same content,
        # same entity ids, so both DD003 and DD005 have something real to point at.
        test_rows = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(8)]
        test_rows += [row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i) for i in range(12)]
    else:
        test_rows = [row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i) for i in range(20)]
    write_rows(root / "test.csv", test_rows, COLUMNS)
    return root


@pytest.fixture
def clean(tmp_path: Path) -> Path:
    return _dataset(tmp_path / "clean", leaky=False)


@pytest.fixture
def leaky(tmp_path: Path) -> Path:
    return _dataset(tmp_path / "leaky", leaky=True)


def _cli(*argv: str) -> int:
    """Run the console entry point the way a shell does, and return its exit code."""
    argv_backup = sys.argv
    sys.argv = ["dataset-doctor", *[str(a) for a in argv]]
    try:
        with pytest.raises(SystemExit) as exit_info:
            main()
    finally:
        sys.argv = argv_backup
    return int(exit_info.value.code or 0)


def _payload(root: Path, outdir: Path) -> dict[str, Any]:
    assert _cli("audit", root, "-o", outdir, "-q") in (0, 1)
    return json.loads((outdir / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ TEST 33: schema
def test_test33_report_json_carries_every_field_the_spec_freezes(clean: Path, tmp_path: Path) -> None:
    payload = _payload(clean, tmp_path / "out")

    assert set(payload) >= REPORT_FIELDS, sorted(REPORT_FIELDS - set(payload))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["findings"], "the fixture must produce at least one finding to check against"
    for finding in payload["findings"]:
        assert set(finding) >= FINDING_FIELDS, sorted(FINDING_FIELDS - set(finding))
        assert re.fullmatch(r"DD\d{3}-\d{4}", finding["finding_id"]), finding["finding_id"]
        assert Severity[finding["severity"].upper()] is not None
        assert finding["why_it_matters"], "a finding that does not say why is not reviewable"
    assert payload["repair_plan"], "the plan is part of the JSON contract, not only of the Markdown"


def test_test33_the_field_set_does_not_depend_on_which_rules_fire(clean: Path, leaky: Path, tmp_path: Path) -> None:
    """A schema that only appears when a rule finds something is not a stable schema."""
    left = _payload(clean, tmp_path / "out_clean")
    right = _payload(leaky, tmp_path / "out_leaky")

    assert set(left) == set(right)
    assert {tuple(sorted(f)) for f in left["findings"]} == {tuple(sorted(f)) for f in right["findings"]}
    assert {tuple(sorted(o)) for o in left["rule_outcomes"]} == {tuple(sorted(o)) for o in right["rule_outcomes"]}
    assert right["eval_safety"] == "FORMAL_EVAL_INVALID"


def test_test33_report_json_round_trips_into_the_model(clean: Path, tmp_path: Path) -> None:
    payload = _payload(clean, tmp_path / "out")
    report = AuditReport.model_validate({key: value for key, value in payload.items() if key != "repair_plan"})

    assert report.schema_version == payload["schema_version"]
    assert [f.finding_id for f in report.findings] == [f["finding_id"] for f in payload["findings"]]


# ----------------------------------------------------- TEST 33 (renderings, no invention)
def test_the_renderers_show_the_verdict_and_the_ids_that_json_carries(clean: Path, tmp_path: Path) -> None:
    outdir = tmp_path / "out"
    assert _cli("audit", clean, "-o", outdir, "-q") in (0, 1)
    payload = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    markdown = (outdir / "report.md").read_text(encoding="utf-8")
    html = (outdir / "report.html").read_text(encoding="utf-8")

    assert payload["eval_safety"] in markdown
    assert payload["eval_safety"] in html
    for finding in payload["findings"]:
        assert finding["finding_id"] in markdown
        assert finding["finding_id"] in html
    assert "<html" in html and "</html>" in html


def test_the_html_report_is_self_contained(clean: Path, tmp_path: Path) -> None:
    """No CDN, no external font: the report has to open on a machine with no network."""
    outdir = tmp_path / "out"
    _cli("audit", clean, "-o", outdir, "-q")
    html = (outdir / "report.html").read_text(encoding="utf-8")

    external = re.findall(r"""(?:src|href)\s*=\s*["'](https?:|//)[^"']*""", html)
    assert external == [], f"report.html pulls external resources: {external}"


# ---------------------------------------------------------------- TEST 21: interruption
def test_test21_an_interrupted_run_exits_130_and_writes_nothing(
    clean: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outdir = tmp_path / "out"

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "audit_dataset", interrupted)
    code = _cli("audit", clean, "-o", outdir)

    assert code == 130
    assert not outdir.exists() or list(outdir.iterdir()) == []


def test_test21_a_failure_while_writing_leaves_the_previous_report_intact(
    clean: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reports are swapped in by rename, so a crash mid-write cannot damage an old report.

    The stray ``report.json.tmp`` left behind is recoverable noise; a truncated
    ``report.json`` would be the actual disaster, and this is what proves it cannot happen.
    """
    outdir = tmp_path / "out"
    payload = _payload(clean, outdir)
    before = (outdir / "report.json").read_text(encoding="utf-8")
    report = audit_dataset(clean).report

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("the disk went away")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError):
        write_reports(report, outdir)

    assert (outdir / "report.json").read_text(encoding="utf-8") == before
    assert json.loads(before)["schema_version"] == payload["schema_version"]


# ------------------------------------------------------------------ TEST 34: exit codes
def test_test34_a_leaky_dataset_exits_1(leaky: Path, tmp_path: Path) -> None:
    assert _cli("audit", leaky, "-o", tmp_path / "out", "-q") == 1


def test_test34_a_clean_dataset_exits_0_without_ci(clean: Path, tmp_path: Path) -> None:
    assert _cli("audit", clean, "-o", tmp_path / "out", "-q") == 0


def test_test34_fail_on_never_overrides_a_blocking_finding(leaky: Path, tmp_path: Path) -> None:
    assert _cli("audit", leaky, "-o", tmp_path / "out", "-q", "--fail-on", "never") == 0


def test_test34_fail_on_thresholds_pick_the_severity_you_ask_for(clean: Path, leaky: Path, tmp_path: Path) -> None:
    # The leaky fixture's duplicates are CRITICAL; the clean one has nothing above LOW.
    assert _cli("audit", leaky, "-o", tmp_path / "a", "-q", "--fail-on", "critical") == 1
    assert _cli("audit", clean, "-o", tmp_path / "b", "-q", "--fail-on", "critical") == 0
    assert _cli("audit", clean, "-o", tmp_path / "c", "-q", "--fail-on", "low") == 1


def test_test34_ci_fails_on_an_inconclusive_verdict_even_though_a_plain_run_does_not(
    tmp_path: Path,
) -> None:
    """ "Not proven" is not "safe", and CI is where that distinction has to bite."""
    root = tmp_path / "train_only"
    root.mkdir(parents=True)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)

    assert _cli("audit", root, "-o", tmp_path / "out", "-q") == 0
    assert _cli("audit", root, "-o", tmp_path / "out", "-q", "--ci") == 1


def test_test34_strict_is_a_superset_of_ci_never_a_looser_gate_with_a_stricter_name(
    clean: Path, leaky: Path, tmp_path: Path
) -> None:
    """Whatever passes ``--ci`` must also pass ``--strict``; the reverse is not true.

    ``--strict`` used to fail on HIGH-and-worse findings only, which is a *lower* bar
    than ``--ci`` (medium-and-worse, or a verdict that is not plainly safe). A team
    tightening their gate with ``--strict`` would have quietly loosened it.
    """
    root = tmp_path / "train_only"
    root.mkdir(parents=True)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)

    assert _cli("audit", clean, "-o", tmp_path / "clean", "-q", "--strict") == 0
    assert _cli("audit", leaky, "-o", tmp_path / "leaky", "-q", "--strict") == 1
    # No test split means no rule could conclude about the boundary; that is exactly
    # the "unproven" case --strict exists for.
    assert _cli("audit", root, "-o", tmp_path / "inconclusive", "-q") == 0
    assert _cli("audit", root, "-o", tmp_path / "inconclusive", "-q", "--ci") == 1
    assert _cli("audit", root, "-o", tmp_path / "inconclusive", "-q", "--strict") == 1


def test_test34_an_unreadable_request_exits_2(tmp_path: Path) -> None:
    assert _cli("audit", tmp_path / "nope", "-o", tmp_path / "out", "-q") == 2
    assert _cli("audit", tmp_path / "nope", "-o", tmp_path / "out", "-q", "--fail-on", "sometimes") == 2


def test_test34_an_internal_error_exits_3_and_names_the_exception(
    clean: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a detector fell over")

    monkeypatch.setattr(cli_module, "audit_dataset", explode)
    code = _cli("audit", clean, "-o", tmp_path / "out", "-q")

    assert code == 3
    assert "a detector fell over" in capsys.readouterr().err


# ------------------------------------------------------------------ the audit entry point
def test_the_result_object_exposes_the_same_verdict_as_the_report(clean: Path) -> None:
    result = audit_dataset(clean)

    assert result.report.eval_safety.value in {"FORMAL_EVAL_SAFE", "FORMAL_EVAL_RISKY", "INCONCLUSIVE"}
    assert result.exit_code() == 0
    assert result.by_rule("DD003") == []
    assert result.rule("DD003") is not None


def test_a_leaky_run_is_reported_as_invalid_and_exposes_the_evidence(leaky: Path) -> None:
    result = audit_dataset(leaky)
    duplicates = result.by_rule("DD003")

    assert result.report.eval_safety.value == "FORMAL_EVAL_INVALID"
    assert duplicates and duplicates[0].status.value in ("FAIL", "WARNING")
    assert duplicates[0].affected_count >= 8
    assert duplicates[0].evidence, "a verdict with no evidence behind it is a guess"
    assert any(record in str(duplicates[0].location.model_dump()) for record in ("r000", "p00")), (
        "the finding must point at rows a human can open"
    )
