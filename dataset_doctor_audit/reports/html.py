"""Self-contained HTML report.

Single file, no external assets: no CDN, no web fonts, no script that could phone
home. The dataset name, its column names and its finding text are rendered into
the page, so a report that fetched a remote stylesheet would be leaking metadata
about data the user never agreed to share (spec prohibition: no cloud upload).

The two graphics are inline SVG generated from the numbers in this report - a
severity bar and a rule-coverage strip - because both answer a question a table
answers badly: "how much of this did the tool actually look at?"
"""

from __future__ import annotations

import html
import json
from typing import Any

from ..models import AuditFinding, AuditReport, Severity
from ..rules import REGISTRY
from .repair import RepairPlan

_COLORS = {
    "CRITICAL": "#c0362c",
    "HIGH": "#e07a2f",
    "MEDIUM": "#d8b129",
    "LOW": "#4a8fd1",
    "INFO": "#7a8290",
}
_STATUS_COLORS = {
    "PASS": "#2e7d4f",
    "FAIL": "#c0362c",
    "WARNING": "#d8b129",
    "INCONCLUSIVE": "#8a6fb0",
    "NOT_RUN": "#b9bfc7",
    "UNSUPPORTED": "#b9bfc7",
    "SUPPRESSED": "#d7dbe0",
}
_VERDICT_COLOR = {
    "FORMAL_EVAL_SAFE": "#2e7d4f",
    "FORMAL_EVAL_RISKY": "#d8b129",
    "FORMAL_EVAL_INVALID": "#c0362c",
    "INCONCLUSIVE": "#8a6fb0",
}


def render_html(report: AuditReport, plan: RepairPlan) -> str:
    body = "".join(
        [
            _header(report),
            _verdict_card(report),
            _identity_card(report),
            _findings(report.findings),
            _coverage(report),
            _repair(plan),
            _notes(report),
        ]
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Dataset Doctor - {esc(report.identity.dataset_id)}</title>"
        f"<style>{_CSS}</style></head><body><main class='wrap'>{body}</main></body></html>"
    )


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


# ------------------------------------------------------------------- fragments
def _header(report: AuditReport) -> str:
    ident = report.identity
    meta = " · ".join(
        [
            f"dataset <code>{esc(ident.dataset_id)}</code>",
            f"{ident.num_samples:,} samples",
            f"config <code>{esc(report.config_hash[:12])}</code>",
            f"tool v{esc(report.tool_version)}",
            f"schema {esc(report.schema_version)}",
            esc(report.generated_at.isoformat()),
            f"{report.duration_ms:,} ms",
        ]
    )
    return (
        f"<header><h1>Dataset Doctor</h1><p class='path'>{esc(ident.root_path)}</p><p class='meta'>{meta}</p></header>"
    )


def _verdict_card(report: AuditReport) -> str:
    color = _VERDICT_COLOR.get(report.eval_safety.value, "#333")
    counts = report.summary.by_severity
    reasons = "".join(f"<li>{esc(item)}</li>" for item in report.eval_safety_reasons)
    return (
        f"<section class='verdict' style='--v:{color}'><div><p class='kicker'>verdict</p>"
        f"<h2>{esc(report.eval_safety.value)}</h2>"
        f"<p class='blocking'>{report.summary.blocking_findings} blocking · "
        f"{report.summary.total_findings} findings</p></div>"
        f"<div>{_severity_bar(counts)}</div></section>"
        f"<p class='reasons'>Why: <span>{reasons}</span></p>"
    )


def _severity_bar(counts: dict[str, int]) -> str:
    total = sum(counts.values()) or 1
    segments = []
    offset = 0.0
    for severity in Severity:
        count = counts.get(severity.value, 0)
        if not count:
            continue
        width = 320.0 * count / total
        segments.append(
            f"<rect x='{offset:.1f}' y='0' width='{max(width - 2, 2):.1f}' height='26' "
            f"rx='4' fill='{_COLORS[severity.value]}'><title>{severity.value}: {count}</title></rect>"
        )
        offset += width
    legend = " ".join(
        f"<span class='chip' style='--c:{_COLORS[s.value]}'>{s.value} <b>{counts.get(s.value, 0)}</b></span>"
        for s in reversed(list(Severity))
    )
    return (
        f"<svg viewBox='0 0 320 26' width='320' height='26' role='img' "
        f"aria-label='findings by severity'>{''.join(segments)}</svg><p class='legend'>{legend}</p>"
    )


def _identity_card(report: AuditReport) -> str:
    ident = report.identity
    splits = "".join(
        f"<tr><td>split <code>{esc(name)}</code></td><td>{count:,}</td></tr>"
        for name, count in sorted(ident.split_sizes.items())
    )
    classes = ident.class_counts
    class_rows = "".join(
        f"<tr><td><code>{esc(name)}</code></td><td>{count:,}</td></tr>"
        for name, count in sorted(classes.items(), key=lambda item: -item[1])[:12]
    )
    more = len(classes) - 12
    if more > 0:
        class_rows += f"<tr><td colspan='2'>+{more} more classes</td></tr>"
    notes = "".join(f"<li>{esc(n)}</li>" for n in report.coverage.get("inference_notes", []))
    return (
        "<section class='card'><h3>What this dataset is</h3><div class='cols'>"
        f"<table><tr><th field>Samples</th><td>{ident.num_samples:,}</td></tr>"
        f"<tr><th field>Type</th><td>{esc(ident.dataset_type.value)}</td></tr>"
        f"<tr><th field>Fingerprint</th><td>{esc(ident.fingerprint_mode.value)}</td></tr>"
        f"<tr><th field>Columns</th><td>{len(ident.schema)}</td></tr>"
        f"<tr><th field>Manifest</th><td><code>{esc(ident.manifest_hash[:16])}</code></td></tr>{splits}</table>"
        f"<table><tr><th field>Classes</th><td>Count</td></tr>{class_rows}</table></div>"
        f"<ul class='notes'>{notes}</ul></section>"
    )


def _findings(findings: list[AuditFinding]) -> str:
    if not findings:
        return (
            "<section class='card'><h3>Findings</h3><p class='empty'>Nothing above INFO. The coverage "
            "table below states which rules were actually able to look at this data.</p></section>"
        )
    ordered = sorted(findings, key=lambda f: (-f.severity.rank, f.finding_id))
    cards = "".join(_finding_card(finding) for finding in ordered)
    return f"<section class='card'><h3>Findings ({len(findings)})</h3>{cards}</section>"


def _finding_card(finding: AuditFinding) -> str:
    rule = REGISTRY.get(finding.rule_id)
    color = _COLORS[finding.severity.value]
    location = _location(finding)
    affected = f"{finding.affected_count:,} samples"
    if finding.affected_ratio is not None:
        affected += f" ({finding.affected_ratio:.1%})"
    evidence = esc(json.dumps(finding.evidence, indent=2, sort_keys=True, default=str, ensure_ascii=False))
    caveats = "".join(f"<li>{esc(item)}</li>" for item in finding.limitations)
    fp_note = f"<p class='fp'><b>False-positive mode:</b> {esc(rule.false_positive_notes)}</p>" if rule else ""
    doc = f"<a class='doc' href='../{esc(rule.doc_path)}'>rule doc</a>" if rule and rule.doc_path else ""
    return (
        f"<details class='finding' style='--s:{color}'><summary>"
        f"<span class='sev'>{esc(finding.severity.value)}</span>"
        f"<span class='fid'>{esc(finding.finding_id)}</span>"
        f"<span class='ftitle'>{esc(finding.title)}</span>"
        f"<span class='badge'>{esc(finding.status.value)}</span>"
        f"<span class='badge impact-{esc(finding.formal_impact.value.lower())}'>"
        f"{esc(finding.formal_impact.value)}</span></summary>"
        f"<div class='body'><p class='loc'>{location} · <b>{affected}</b> · "
        f"evidence {esc(finding.evidence_type.value)} · confidence {esc(finding.confidence.value)} · "
        f"rule {esc(finding.rule_id)} {esc(rule.name if rule else '')} {doc}</p>"
        f"<p>{esc(finding.description)}</p>"
        f"<p class='why'>{esc(finding.why_it_matters)}</p>"
        f"<p class='do'><b>Do:</b> {esc(finding.recommended_action)}</p>"
        f"{'<ul class=caveats>' + caveats + '</ul>' if caveats else ''}"
        f"{fp_note}"
        f"<details class='evidence'><summary>Evidence ({len(evidence.splitlines())} lines of JSON)</summary>"
        f"<pre>{evidence}</pre></details></div></details>"
    )


def _location(finding: AuditFinding) -> str:
    if finding.source_split and finding.target_split:
        return f"<code>{esc(finding.source_split)}</code> ↔ <code>{esc(finding.target_split)}</code>"
    if finding.source_split:
        return f"split <code>{esc(finding.source_split)}</code>"
    if finding.location.columns:
        return "columns " + ", ".join(f"<code>{esc(c)}</code>" for c in finding.location.columns[:6])
    if finding.location.paths:
        return f"{len(finding.location.paths)} file(s)"
    return "dataset-wide"


def _coverage(report: AuditReport) -> str:
    strip = "".join(
        f"<rect x='{i * 15}' y='0' width='13' height='13' rx='3' fill='{_STATUS_COLORS.get(o.status.value, '#999')}'>"
        f"<title>{o.rule_id}: {o.status.value}</title></rect>"
        for i, o in enumerate(report.rule_outcomes)
    )
    legend = " ".join(f"<span class='chip' style='--c:{color}'>{name}</span>" for name, color in _STATUS_COLORS.items())
    row_parts: list[str] = []
    for outcome in report.rule_outcomes:
        rule = REGISTRY.get(outcome.rule_id)
        row_parts.append(
            "<tr>"
            f"<td><code>{esc(outcome.rule_id)}</code></td>"
            f"<td>{esc(rule.name if rule else '-')}</td>"
            f"<td><span class='pill' style='--c:{_STATUS_COLORS.get(outcome.status.value, '#999')}'>"
            f"{esc(outcome.status.value)}</span></td>"
            f"<td class='num'>{outcome.finding_count}</td>"
            f"<td>{esc(outcome.highest_severity.value) if outcome.highest_severity else '-'}</td>"
            f"<td class='note'>{esc(_clip(outcome.skip_reason or outcome.suppression_reason or ''))}</td>"
            f"<td class='num'>{outcome.duration_ms} ms</td></tr>"
        )
    rows = "".join(row_parts)
    cov = report.coverage
    stats = " · ".join(
        [
            f"rules attempted {cov.get('rules_attempted', 0)}/{cov.get('rules_total', 0)}",
            f"fingerprint {esc(cov.get('fingerprint_mode'))}",
            f"sample fraction {cov.get('sample_fraction')}",
            f"python {esc(cov.get('python'))}",
            f"{esc(cov.get('platform'))}",
        ]
    )
    return (
        "<section class='card'><h3>Rule coverage</h3>"
        f"<svg viewBox='0 0 {max(15 * len(report.rule_outcomes), 15)} 13' height='13' "
        f"width='{max(15 * len(report.rule_outcomes), 15)}' role='img'>{strip}</svg>"
        f"<p class='legend'>{legend}</p><p class='meta'>{stats}</p>"
        "<table class='rules'><tr><th>ID</th><th>Rule</th><th>Status</th><th>Findings</th>"
        f"<th>Max severity</th><th>Why not / note</th><th>Time</th></tr>{rows}</table></section>"
    )


def _repair(plan: RepairPlan) -> str:
    if not plan.steps:
        return "<section class='card'><h3>Repair plan</h3><p class='empty'>Nothing actionable.</p></section>"
    items = []
    for step in plan.steps:
        command = f"<pre class='cmd'>{esc(step.command)}</pre>" if step.command else ""
        marker = "<span class='tag'>writes a new directory</span>" if step.writes_data else ""
        items.append(
            f"<li><b>{esc(step.title)}</b> {marker}<p>{esc(step.action)}</p>{command}"
            f"<p class='why'><b>Resolves</b> {esc(', '.join(step.removes_findings) or 'verification only')} · "
            f"{esc(step.why_now)}</p>"
            + (f"<p class='fp'><b>Residual risk:</b> {esc(step.residual_risk)}</p>" if step.residual_risk else "")
            + "</li>"
        )
    unresolved = (
        f"<p class='empty'>Not addressed by any step: {esc(', '.join(plan.unresolved))}</p>" if plan.unresolved else ""
    )
    notes = "".join(f"<li>{esc(note)}</li>" for note in plan.notes)
    return (
        "<section class='card'><h3>Repair plan</h3>"
        "<p class='meta'>Ordered by dependency, not by severity: a fix that changes row identity must "
        f"run before the split is rebuilt.</p><ol>{''.join(items)}</ol>{unresolved}"
        f"<ul class='notes'>{notes}</ul></section>"
    )


def _notes(report: AuditReport) -> str:
    method = "".join(f"<li>{esc(item)}</li>" for item in report.methodology)
    limits = "".join(f"<li>{esc(item)}</li>" for item in report.limitations)
    warnings = "".join(f"<li>{esc(item)}</li>" for item in report.coverage.get("config_warnings", []))
    adapter = "".join(f"<li>{esc(item)}</li>" for item in report.coverage.get("adapter_notes", []))
    return (
        "<section class='card'><h3>How this was decided</h3>"
        f"<details><summary>Methodology</summary><ol>{method}</ol></details>"
        f"<details open><summary>Limitations - read before quoting this report</summary><ol>{limits}</ol></details>"
        f"<details><summary>Tooling notes</summary><ul>{warnings}{adapter}</ul></details></section>"
        "<footer>Generated locally by Dataset Doctor. No dataset content left this machine: the report "
        "embeds counts, hashes and column names only, and references no external asset.</footer>"
    )


def _clip(text: str, limit: int = 90) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


_CSS = """
:root{color-scheme:light dark;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#1c2128}
.wrap{max-width:1000px;margin:0 auto;padding:32px 20px 80px}
header h1{margin:0;font-size:26px;letter-spacing:-.4px}
.path{margin:2px 0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#404750}
.meta,.kicker{color:#6b7280;font-size:12px}
.kicker{text-transform:uppercase;letter-spacing:.09em;margin:0}
.card,section.verdict{background:#fff;border:1px solid #e3e6ea;border-radius:12px;padding:18px 20px;margin:16px 0;
box-shadow:0 1px 2px rgba(16,22,26,.05)}
section.verdict{border-left:6px solid var(--v)}
section.verdict h2{margin:4px 0;font-size:22px;color:var(--v)}
.verdict{display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap}
.blocking{font-size:13px;color:#6b7280}
.reasons{font-size:13px}.reasons>span{display:block}
.legend{margin:8px 0 0;font-size:11px}
.chip{display:inline-block;margin-right:8px;padding:1px 7px;border-radius:999px;color:#fff;background:var(--c);font-weight:600}
h3{margin:0 0 10px;font-size:16px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #eceef1;vertical-align:top}
th{color:#6b7280;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
th[field]{color:#1c2128;text-transform:none;font-weight:600;letter-spacing:0;width:38%}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.finding{border:1px solid #e3e6ea;border-left:4px solid var(--s);border-radius:9px;margin:9px 0;background:#fcfcfd}
.finding>summary{cursor:pointer;padding:10px 12px;display:flex;gap:9px;align-items:center;flex-wrap:wrap;list-style:none}
.finding>summary::-webkit-details-marker{display:none}
.sev{font-size:10px;font-weight:700;color:#fff;background:var(--s);padding:2px 7px;border-radius:5px;min-width:62px;text-align:center}
.fid{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#6b7280}
.ftitle{font-weight:600;font-size:14px}
.badge{font-size:10px;border:1px solid #d5d9de;color:#5a626c;padding:1px 6px;border-radius:5px}
.impact-blocking{background:#c0362c;color:#fff;border-color:#c0362c}
.impact-potential{background:#d8b129;color:#3b2f00;border-color:#d8b129}
.body{padding:0 14px 12px;border-top:1px dashed #e3e6ea}
.loc{font-size:12px;color:#6b7280}
.why{font-style:italic;color:#404750;font-size:13px}
.do{font-size:13px;background:#f2f7f4;border-left:3px solid #2e7d4f;padding:7px 10px;border-radius:0 6px 6px 0}
.caveats,.notes,.fp{font-size:12px;color:#7a6100}
.fp{color:#8a6fb0}
.evidence summary{font-size:12px;color:#6b7280;cursor:pointer;margin-top:6px}
pre{background:#14181d;color:#e6e8ea;padding:11px;border-radius:8px;overflow:auto;font-size:11.5px;line-height:1.5}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.92em;background:#eef0f2;padding:1px 4px;border-radius:4px}
.pill{font-size:10px;font-weight:700;color:#fff;background:var(--c);padding:2px 7px;border-radius:5px}
.note{font-size:11.5px;color:#6b7280}
ol{padding-left:22px;font-size:13.5px}ol li{margin:12px 0}
.tag{font-size:10px;background:#e7f0ea;color:#2e7d4f;padding:1px 6px;border-radius:5px}
.empty{font-size:13px;color:#6b7280}
.doc{font-size:11px;color:#4a8fd1}
footer{font-size:11.5px;color:#6b7280;margin-top:26px;text-align:center}
@media(prefers-color-scheme:dark){body{background:#0f1216;color:#dee2e6}
.card,section.verdict,pre{background:#161b21;border-color:#252b33;box-shadow:none}
.path,.meta,.kicker,.note,.empty,.loc,.blocking,footer{color:#98a1ab}
th{color:#98a1ab}td,th{border-color:#242a31}.finding{background:#13181e}
code{background:#20262d}.do{background:#132018}.pill{color:#0f1216}}
@media print{.wrap{max-width:none}pre{white-space:pre-wrap}.finding{break-inside:avoid}}
"""
