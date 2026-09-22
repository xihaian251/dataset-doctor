"""Ordered repair plan: the difference between a list of problems and a fix.

A finding on its own says "something is wrong". A reviewer needs the *sequence* -
some fixes invalidate the evidence for others (de-duplicating before re-splitting,
re-splitting before re-auditing), so the plan is sorted by dependency, not by
severity. Every step states what it removes and what it cannot remove, because
"will this make the finding go away?" is the first question people ask and a tool
that cannot answer it is just a linter with extra steps.

Nothing here writes to the dataset: steps that change data emit a command that
creates a *new* output directory (spec prohibitions: never overwrite, never auto-delete).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import AuditFinding, Severity

# Lower runs first. 0 = declare what the dataset is, 1 = remove damaged samples,
# 2 = de-duplicate, 3 = re-split (the big one), 4 = re-verify.
_ORDER = {
    "declare": 0,
    "remove": 1,
    "deduplicate": 2,
    "resplit": 3,
    "review": 4,
    "recalibrate": 5,
    "verify": 6,
}


@dataclass
class RepairStep:
    order: int
    kind: str
    title: str
    action: str
    why_now: str
    removes_findings: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    command: str | None = None
    writes_data: bool = False
    residual_risk: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.order,
            "kind": self.kind,
            "title": self.title,
            "action": self.action,
            "why_now": self.why_now,
            "command": self.command,
            "writes_new_directory": self.writes_data,
            "rule_ids": self.rule_ids,
            "resolves_findings": self.removes_findings,
            "residual_risk": self.residual_risk,
        }


@dataclass
class RepairPlan:
    steps: list[RepairStep]
    unresolved: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.as_dict() for step in self.steps],
            "unresolved_findings": self.unresolved,
            "notes": self.notes,
        }


def build_repair_plan(findings: list[AuditFinding], root: str = ".", baseline_hint: bool = True) -> RepairPlan:
    """Group findings into the order a human should actually work them in."""
    buckets: dict[str, list[AuditFinding]] = {}
    for finding in findings:
        if finding.severity is Severity.INFO and finding.status.value == "PASS":
            continue
        buckets.setdefault(_kind_of(finding), []).append(finding)

    steps: list[RepairStep] = []
    for kind, group in buckets.items():
        steps.append(_step_for(kind, group, root))
    if baseline_hint:
        steps.append(_reverify_step(root, steps))
    steps.sort(key=lambda step: step.order)
    for number, step in enumerate(steps, start=1):
        step.order = number

    covered = {fid for step in steps for fid in step.removes_findings}
    unresolved = [
        f.finding_id for f in findings if f.finding_id not in covered and f.severity.rank >= Severity.LOW.rank
    ]
    notes = [
        "Every step that touches data writes to a new directory; the original dataset is never modified.",
        "Re-audit after each structural step: a fix that is not re-measured is a fix that is not verified.",
    ]
    return RepairPlan(steps=steps, unresolved=unresolved, notes=notes)


def _kind_of(finding: AuditFinding) -> str:
    rule = finding.rule_id
    if rule == "DD020":
        return "declare"
    if rule == "DD016":
        return "remove"
    if rule in {"DD003", "DD004"}:
        return "deduplicate"
    if rule in {"DD005", "DD006", "DD009"}:
        return "resplit"
    if rule in {"DD007", "DD008", "DD014", "DD021", "DD002"}:
        return "review"
    if rule in {"DD011", "DD012", "DD013", "DD015", "DD017"}:
        return "recalibrate"
    return "review"


def _step_for(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    builder = {
        "declare": _declare,
        "remove": _remove,
        "deduplicate": _deduplicate,
        "resplit": _resplit,
        "review": _review,
        "recalibrate": _recalibrate,
    }.get(kind, _review)
    return builder(kind, group, root)


def _first(group: list[AuditFinding]) -> AuditFinding:
    return sorted(group, key=lambda f: -f.severity.rank)[0]


def _declare(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    return RepairStep(
        _ORDER[kind],
        kind,
        "Declare the dataset contract",
        "Run `dataset-doctor-audit init` and fill in labels.column, groups.columns, "
        "temporal.column and the split layout.",
        "Half the rules can only answer INCONCLUSIVE without declared metadata; declaring it "
        "first converts guesses into measurements and costs minutes.",
        [f.finding_id for f in group],
        sorted({f.rule_id for f in group}),
        f"dataset-doctor-audit init {root}",
    )


def _remove(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    files = sorted({path for f in group for path in f.location.paths})
    return RepairStep(
        _ORDER[kind],
        kind,
        "Quarantine unreadable samples",
        f"{len(files) or 'Several'} file(s) could not be decoded; the finding evidence lists them. Move "
        "them out of the split rather than deleting them: a corrupt file that is silently dropped "
        "changes the denominator of every statistic.",
        "Corrupt samples poison property statistics and silently reduce coverage; removing them "
        "before de-duplication keeps duplicate counts honest.",
        [f.finding_id for f in group],
        sorted({f.rule_id for f in group}),
        f"mkdir -p {root}-quarantine && mv {' '.join(files[:5]) or '<paths listed in the report>'} {root}-quarantine/",
        writes_data=True,
        residual_risk="Manual step by design: the tool will not delete your data.",
    )


def _deduplicate(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    cross = [f for f in group if f.metadata.get("scope") == "cross_split"]
    return RepairStep(
        _ORDER[kind],
        kind,
        "Collapse exact duplicates before splitting",
        f"{len(cross)} cross-split duplicate group(s) and {len(group) - len(cross)} within-split "
        "group(s). Keep one member per hash and record which was dropped; the finding evidence lists "
        "each hash with its sample ids.",
        "De-duplication changes row identity, so it must precede the split; otherwise the same "
        "content can land on both sides again.",
        [f.finding_id for f in group],
        sorted({f.rule_id for f in group}),
        f"dataset-doctor-audit split {root} --dedupe --output {root}-deduped",
        writes_data=True,
        residual_risk="De-duplicating a benchmark you did not build can change its published metrics.",
    )


def _resplit(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    columns: list[str] = []
    for finding in group:
        column = finding.evidence.get("group_column") or finding.evidence.get("column")
        if column and column not in columns:
            columns.append(str(column))
    flag = f" --group-by {columns[0]}" if columns else ""
    ids = ", ".join(sorted(columns)) or "the entity column"
    return RepairStep(
        _ORDER[kind],
        kind,
        "Rebuild the split so shared entities and labels stop crossing",
        f"Entity/label leakage on {ids}: samples that must not be seen twice are in more than one "
        "split. Regenerate the split grouped by that key instead of shuffling rows.",
        "This is the only class of finding that can make a bad model look good; every later "
        "measurement is computed on the wrong partition until it is fixed.",
        [f.finding_id for f in group],
        sorted({f.rule_id for f in group}),
        f"dataset-doctor-audit split {root}{flag} --output {root}-resplit",
        writes_data=True,
        residual_risk="A grouped split is coarser: effective sample count drops and class balance may shift.",
    )


def _review(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    top = _first(group)
    return RepairStep(
        _ORDER[kind],
        kind,
        "Human review: semantics the data cannot answer",
        f"{top.title}. Decide, per column, whether the value existed before the outcome happened. "
        "No statistic can distinguish a strong biomarker from a post-outcome measurement.",
        "These are candidates, not verdicts; acting on them mechanically would delete real signal.",
        [f.finding_id for f in group],
        sorted({f.rule_id for f in group}),
        None,
        residual_risk="Dropping a column that turns out to be legitimate loses accuracy you cannot get back.",
    )


def _recalibrate(kind: str, group: list[AuditFinding], root: str) -> RepairStep:
    top = _first(group)
    return RepairStep(
        _ORDER[kind],
        kind,
        "Decide whether the distribution difference is the dataset",
        f"{top.title}. If the population genuinely differs, fix the evaluation (weighted metrics, "
        "per-segment reporting) rather than resampling the data into agreement.",
        "Shift is a fact about the world; 'fixing' it by resampling hides the very effect the "
        "model will be measured on.",
        [f.finding_id for f in group],
        sorted({f.rule_id for f in group}),
        f"dataset-doctor-audit audit {root} --policy research  # tighten or loosen thresholds deliberately",
    )


def _reverify_step(root: str, prior: list[RepairStep]) -> RepairStep:
    return RepairStep(
        _ORDER["verify"],
        "verify",
        "Re-audit and snapshot the fixed dataset",
        "Re-run the audit on the new output and diff it against this baseline, so the report shows "
        "which findings actually disappeared.",
        "A fix that was never re-measured is a claim, not a result.",
        [],
        ["DD018", "DD019"],
        f"dataset-doctor-audit audit {root} --save-snapshot fixed"
        f" && dataset-doctor-audit diff {root} --baseline current",
    )
