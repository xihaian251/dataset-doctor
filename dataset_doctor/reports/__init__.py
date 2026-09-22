"""Report writers. JSON is authoritative; Markdown and HTML are renderings of it.

The order is deliberate: anything a reviewer can act on must be reconstructible
from ``report.json`` alone, so the Markdown and HTML layers are not allowed to
invent fields. That is also why the repair plan is computed once here and passed
into both renderers - two plans that disagree would be worse than none.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..models import AuditReport
from .html import render_html
from .markdown import render_markdown
from .repair import RepairPlan, build_repair_plan

FORMATS = ("json", "md", "html")


def write_reports(
    report: AuditReport,
    outdir: Path | str,
    formats: tuple[str, ...] = FORMATS,
    plan: RepairPlan | None = None,
    diff: dict[str, Any] | None = None,
) -> list[Path]:
    """Write the requested formats atomically and return the paths created."""
    unknown = [fmt for fmt in formats if fmt not in FORMATS]
    if unknown:
        raise ValueError(f"unknown report format(s): {unknown}. Choose from {FORMATS}")
    destination = Path(outdir)
    destination.mkdir(parents=True, exist_ok=True)
    plan = plan or build_repair_plan(report.findings, root=report.identity.root_path)
    written: list[Path] = []
    if "json" in formats:
        written.append(_write(destination / "report.json", json_payload(report, plan, diff)))
    if "md" in formats:
        written.append(_write(destination / "report.md", render_markdown(report, plan, diff)))
    if "html" in formats:
        written.append(_write(destination / "report.html", render_html(report, plan)))
    return written


def json_payload(report: AuditReport, plan: RepairPlan | None = None, diff: dict[str, Any] | None = None) -> str:
    payload = report.model_dump(mode="json")
    payload["repair_plan"] = plan.as_dict() if plan else None
    if diff is not None:
        payload["diff"] = diff
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write(path: Path, text: str) -> Path:
    """Temp file + rename: a killed run leaves the previous report intact, not half a new one."""
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


__all__ = ["FORMATS", "build_repair_plan", "json_payload", "render_html", "render_markdown", "write_reports"]
