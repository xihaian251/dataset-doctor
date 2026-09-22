"""Markdown report - the one a human pastes into a PR.

Ordered so the first screen answers the only three questions that matter: can I
trust this dataset, what exactly is wrong, and what do I do first. Evidence comes
after the claim, never before it.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import AuditFinding, AuditReport, Severity
from ..rules import REGISTRY
from .repair import RepairPlan

_HEADLINE = {
    "FORMAL_EVAL_SAFE": "no finding blocks a formal evaluation on this dataset",
    "FORMAL_EVAL_RISKY": "usable for exploration, but at least one unverified risk would weaken a formal claim",
    "FORMAL_EVAL_INVALID": "do not report a formal metric from this split until the blocking findings are resolved",
    "INCONCLUSIVE": "the tool could not cover enough of the dataset to answer either way",
}


def render_markdown(report: AuditReport, plan: RepairPlan, diff_summary: dict[str, Any] | None = None) -> str:
    parts = [
        _title(report),
        _verdict(report),
        _identity(report),
        _findings_section(report.findings),
        _coverage(report),
        _repair(plan),
    ]
    if diff_summary:
        parts.append(_diff(diff_summary))
    parts += [_prose("Methodology", report.methodology), _prose("Limitations", report.limitations)]
    return "\n\n".join(block for block in parts if block.strip()) + "\n"


def _title(report: AuditReport) -> str:
    return (
        f"# Dataset Doctor Report - `{report.identity.root_path}`\n\n"
        f"`tool {report.tool_version}` · `schema {report.schema_version}` · "
        f"`generated {report.generated_at.isoformat()}` · "
        f"`dataset {report.identity.dataset_id}` · `config {report.config_hash[:12]}` · "
        f"`{report.duration_ms} ms`"
    )


def _verdict(report: AuditReport) -> str:
    counts = report.summary.by_severity
    line = " | ".join(
        f"**{counts.get(s.value, 0)}** {s.value}"
        for s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
    )
    reasons = "\n".join(f"- {reason}" for reason in report.eval_safety_reasons) or "- (none recorded)"
    return (
        f"## Verdict\n\n"
        f"> ### {report.eval_safety.value}\n"
        f"> {_HEADLINE.get(report.eval_safety.value, '')}\n\n"
        f"{line}\n\n"
        f"Blocking findings: **{report.summary.blocking_findings}**. Why this verdict:\n\n{reasons}"
    )


def _identity(report: AuditReport) -> str:
    identity = report.identity
    splits = ", ".join(f"`{name}`: {count}" for name, count in sorted(identity.split_sizes.items()))
    classes = identity.classes
    shown = ", ".join(f"`{c}` ({identity.class_counts[c]})" for c in classes[:12])
    if len(classes) > 12:
        shown += f", +{len(classes) - 12} more"
    rows = [
        ("Samples", f"{identity.num_samples:,}"),
        ("Type", identity.dataset_type.value),
        ("Splits", splits or "-"),
        ("Classes", f"{len(classes)}" + (f" - {shown}" if shown else "")),
        ("Columns", str(len(identity.schema)) if identity.schema else "n/a"),
        ("Fingerprint", f"{identity.fingerprint_mode.value}"),
        ("Manifest hash", f"`{identity.manifest_hash[:16]}`"),
    ]
    table = "\n".join(f"| {label} | {value} |" for label, value in rows)
    schema = _schema_table(identity.schema)
    return f"## Dataset identity\n\n| Field | Value |\n| --- | --- |\n{table}\n{schema}"


def _schema_table(schema: dict[str, str]) -> str:
    if not schema:
        return ""
    cells = ", ".join(f"`{name}`*({dtype})*" for name, dtype in sorted(schema.items()))
    return f"\nColumns: {cells}"


def _findings_section(findings: list[AuditFinding]) -> str:
    if not findings:
        return (
            "## Findings\n\nNo finding above INFO. Read together with the coverage table below: "
            "rules that could not be measured are reported as INCONCLUSIVE, not as PASS."
        )
    ordered = sorted(findings, key=lambda f: (-f.severity.rank, f.finding_id))
    blocks = [f"## Findings ({len(findings)})\n"]
    for finding in ordered:
        blocks.append(_finding(finding))
    return "\n\n".join(blocks)


def _finding(finding: AuditFinding) -> str:
    rule = REGISTRY.get(finding.rule_id)
    name = rule.name if rule else finding.rule_id
    header = (
        f"### {finding.finding_id} - {finding.title}\n\n"
        f"`{finding.severity.value}` · {finding.status.value} · formal impact "
        f"`{finding.formal_impact.value}` · evidence `{finding.evidence_type.value}` · "
        f"confidence `{finding.confidence.value}` · rule **{finding.rule_id}** {name}"
    )
    scope = _scope_line(finding)
    affected = (
        f"**Affected:** {finding.affected_count:,} sample(s)"
        + (f" ({finding.affected_ratio:.1%})" if finding.affected_ratio is not None else "")
        + (" · auto-fix available" if finding.auto_fix_available else " · no automatic fix")
    )
    blocks = [
        header,
        f"{scope}  \n{finding.description}",
        f"*Why it matters:* {finding.why_it_matters}",
        affected,
    ]
    if finding.recommended_action:
        blocks.append(f"**Do:** {finding.recommended_action}")
    if finding.limitations:
        blocks.append("**Caveats:**\n" + "\n".join(f"- {item}" for item in finding.limitations))
    if finding.evidence:
        blocks.append(
            "<details><summary>Evidence</summary>\n\n```json\n" + _json(finding.evidence) + "\n```\n\n</details>"
        )
    ids = finding.location.sample_ids or finding.affected_samples
    if ids:
        preview = ", ".join(f"`{item}`" for item in ids[:10])
        more = f" (+{len(ids) - 10} more)" if len(ids) > 10 else ""
        blocks.append(f"Samples: {preview}{more}")
    if rule and rule.false_positive_notes:
        blocks.append(f"_Known false-positive mode:_ {rule.false_positive_notes}")
    if rule and rule.doc_path:
        blocks.append(f"Rule doc: `{rule.doc_path}`")
    return "\n\n".join(blocks)


def _scope_line(finding: AuditFinding) -> str:
    if finding.source_split and finding.target_split:
        return f"**Where:** `{finding.source_split}` <-> `{finding.target_split}` (cross-split)"
    if finding.source_split:
        return f"**Where:** split `{finding.source_split}`"
    if finding.location.columns:
        return "**Where:** columns " + ", ".join(f"`{c}`" for c in finding.location.columns[:8])
    if finding.location.paths:
        return f"**Where:** {len(finding.location.paths)} file(s), starting " + ", ".join(
            f"`{p}`" for p in finding.location.paths[:3]
        )
    return f"**Where:** dataset-wide ({finding.metadata.get('scope', 'dataset')})"


def _coverage(report: AuditReport) -> str:
    rows = [
        "| Rule | Name | Status | Findings | Highest severity | Note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for outcome in report.rule_outcomes:
        rule = REGISTRY.get(outcome.rule_id)
        note = outcome.skip_reason or outcome.suppression_reason or ""
        severity = outcome.highest_severity.value if outcome.highest_severity else "-"
        rows.append(
            f"| {outcome.rule_id} | {rule.name if rule else '-'} | {outcome.status.value} | "
            f"{outcome.finding_count} | {severity} | {_clip(note, 70)} |"
        )
    coverage = report.coverage
    gaps = {
        "Fingerprint mode": coverage.get("fingerprint_mode"),
        "Sample fraction": coverage.get("sample_fraction"),
        "Rules attempted": f"{coverage.get('rules_attempted', 0)}/{coverage.get('rules_total', 0)}",
        "INCONCLUSIVE": ", ".join(coverage.get("rules_inconclusive", [])) or "-",
        "Not run": ", ".join(coverage.get("rules_not_run", [])) or "-",
        "Suppressed": ", ".join(coverage.get("rules_suppressed", [])) or "-",
    }
    gap_rows = "\n".join(f"| {key} | {value} |" for key, value in gaps.items())
    notes = list(coverage.get("adapter_notes") or []) + list(coverage.get("inference_notes") or [])
    note_block = "\n\nNotes from discovery:\n" + "\n".join(f"- {item}" for item in notes) if notes else ""
    return (
        "## Rule coverage\n\n"
        "A rule that could not run is listed as such; PASS means the detector covered the data.\n\n"
        + "\n".join(rows)
        + f"\n\n| Coverage | Value |\n| --- | --- |\n{gap_rows}"
        + note_block
    )


def _repair(plan: RepairPlan) -> str:
    if not plan.steps:
        return "## Repair plan\n\nNothing actionable."
    rows = ["## Repair plan\n", "Run in this order; later steps depend on earlier ones.\n"]
    for step in plan.steps:
        lines = [f"**{step.title}**"]
        if step.writes_data:
            lines[0] += " _(writes a new directory; original untouched)_"
        lines += ["", step.action]
        if step.command:
            lines += ["", "```", step.command, "```"]
        lines += [
            "",
            f"_Resolves:_ {', '.join(step.removes_findings) or 'verification only'}",
            f"_Why now:_ {step.why_now}",
        ]
        if step.residual_risk:
            lines += ["", f"_Residual risk:_ {step.residual_risk}"]
        body = "\n".join(f"   {line}" if line else "" for line in lines)
        rows.append(f"{step.order}. {body}".rstrip())
    if plan.unresolved:
        rows.append(f"\nStill open after the plan is executed as written: {', '.join(plan.unresolved)}.")
    rows += ["", *[f"- {note}" for note in plan.notes]]
    return "\n".join(rows)


def _diff(summary: dict[str, Any]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in summary.items())
    return f"## Change since baseline\n\n| Metric | Value |\n| --- | --- |\n{rows}"


def _prose(heading: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"## {heading}\n\n" + "\n".join(f"{n}. {item}" for n, item in enumerate(items, start=1))


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=False)


def _clip(text: str, limit: int) -> str:
    text = text.replace("\n", " ").replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"
