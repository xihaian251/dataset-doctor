"""Command line surface.

Exit codes are part of the product (spec section 80): 0 nothing blocking, 1 a finding
that invalidates a formal evaluation, 2 the tool was told something impossible, 3 the
tool itself broke. Anything else makes CI unusable - a warning about class imbalance
must not fail a build that only asked "is my test set contaminated?".
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table

from . import __version__
from .audit import (
    AuditResult,
    audit_dataset,
    diff_targets,
    load_config,
    scan,
    snapshot_dataset,
)
from .config import Config, write_init_template
from .errors import ConfigError, DatasetDoctorError, SplitError
from .models import (
    AuditReport,
    AuditStatus,
    DatasetType,
    EvalSafety,
    FingerprintMode,
    Severity,
)
from .reports import build_repair_plan, write_reports
from .rules import REGISTRY
from .snapshots import list_snapshots, snapshot_summary
from .splitting import SplitRequest, split_dataset

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="Detect data leakage before it corrupts your ML experiment.",
)
console = Console()
error_console = Console(stderr=True, style="bold")

_VERDICT_STYLE = {
    EvalSafety.FORMAL_EVAL_SAFE: "green",
    EvalSafety.FORMAL_EVAL_RISKY: "yellow",
    EvalSafety.FORMAL_EVAL_INVALID: "red",
    EvalSafety.INCONCLUSIVE: "magenta",
}
_SEVERITY_STYLE = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "dim",
}
_STATUS_STYLE = {
    AuditStatus.PASS: "green",
    AuditStatus.FAIL: "red",
    AuditStatus.WARNING: "yellow",
    AuditStatus.INCONCLUSIVE: "magenta",
    AuditStatus.NOT_RUN: "dim",
    AuditStatus.UNSUPPORTED: "dim",
    AuditStatus.SUPPRESSED: "dim",
}


# ------------------------------------------------------------------------ init
@app.command()
def init(
    path: Path = typer.Argument(Path(), help="Where to write dataset-doctor.yaml."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config file."),
) -> None:
    """Write a commented ``dataset-doctor.yaml`` next to your data."""
    target = Path(path)
    file = target if target.suffix else target / "dataset-doctor.yaml"
    if not force and file.exists():
        raise typer.BadParameter(f"{file} already exists (use --force to overwrite)")
    file.parent.mkdir(parents=True, exist_ok=True)
    write_init_template(file)
    console.print(f"[green]wrote[/green] {file}")
    console.print(
        "[dim]Fill in labels.column, groups.columns and temporal.column - every field you declare "
        "turns an INCONCLUSIVE rule into a measured one.[/dim]"
    )


# ------------------------------------------------------------------------ scan
@app.command("scan")
def scan_cmd(
    path: Path = typer.Argument(Path(), help="Dataset root (or one table file)."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="dataset-doctor.yaml"),
    preset: Optional[str] = typer.Option(
        None, "--preset", "--policy", help="standard|medical|vision|time_series|research"
    ),
    fingerprint: Optional[str] = typer.Option(None, "--fingerprint", help="metadata|full|sampled"),
    workers: int = typer.Option(0, "--workers", help="Hashing threads (0 = auto)."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Show what would be audited: layout, splits, samples, schema. Runs no rules."""
    cfg = _load(path, config, preset, fingerprint, workers)
    with _progress(enabled=not quiet) as hook:
        result = scan(path, config=cfg, progress=hook)
    if quiet:
        console.print(json.dumps(_scan_dict(result), indent=2, sort_keys=True))
        return
    table = Table(title=f"{result.identity.root_path} - {result.identity.num_samples:,} samples", show_lines=False)
    table.add_column("Split", overflow="fold")
    table.add_column("Samples", justify="right")
    table.add_column("Labelled", justify="right")
    by_split = result.manifest.by_split()
    for name, records in by_split.items():
        labelled = sum(1 for record in records if record.label)
        table.add_row(name, f"{len(records):,}", f"{labelled:,}" if labelled or name != "all" else "-")
    console.print(table)
    if result.identity.schema:
        columns = ", ".join(f"[bold]{k}[/]({v})" for k, v in sorted(result.identity.schema.items())[:24])
        console.print(f"Columns: {columns}")
    for note in result.spec.inference_notes + list(result.ctx.adapter.notes):
        console.print(f"[dim]- {note}[/dim]")
    console.print(
        f"fingerprint [cyan]{result.manifest.mode.value}[/cyan]  "
        f"dataset [cyan]{result.identity.dataset_id}[/cyan]  "
        f"manifest [cyan]{result.identity.manifest_hash[:16]}[/cyan]"
    )


# ------------------------------------------------------------------------ audit
@app.command()
def audit(
    path: Path = typer.Argument(Path(), help="Dataset root (or one table file)."),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    preset: Optional[str] = typer.Option(None, "--preset", "--policy"),
    fingerprint: Optional[str] = typer.Option(None, "--fingerprint", help="metadata|full|sampled"),
    dataset_type: Optional[str] = typer.Option(None, "--type", help="tabular|image"),
    label_column: Optional[str] = typer.Option(None, "--label-column"),
    group_by: Optional[list[str]] = typer.Option(None, "--group-by", help="Entity column; repeatable."),
    temporal_column: Optional[str] = typer.Option(None, "--temporal-column"),
    split_column: Optional[str] = typer.Option(None, "--split-column", help="Split lives inside a column."),
    id_column: Optional[list[str]] = typer.Option(None, "--id-column"),
    sample: Optional[float] = typer.Option(None, "--sample", min=0.001, max=1.0, help="Fraction of samples to hash."),
    output: Path = typer.Option(Path("dataset-doctor-report"), "--output", "-o", help="Report directory."),
    formats: Optional[list[str]] = typer.Option(None, "--format", "-f", help="json|md|html (repeatable)."),
    baseline: Optional[str] = typer.Option(None, "--baseline", help="Snapshot name or file to diff against."),
    save_snapshot: Optional[str] = typer.Option(None, "--save-snapshot", help="Store a snapshot under this name."),
    ci: bool = typer.Option(False, "--ci", help="Fail on medium-and-worse findings."),
    strict: bool = typer.Option(
        False, "--strict", help="Everything --ci fails on, plus rules that could not conclude."
    ),
    fail_on: Optional[str] = typer.Option(None, "--fail-on", help="never|low|medium|high|critical"),
    workers: int = typer.Option(0, "--workers"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show every rule, not only findings."),
) -> None:
    """Audit a dataset and write JSON + Markdown + HTML reports."""
    cfg = _load(path, config, preset, fingerprint, workers, dataset_type, sample, no_cache)
    cfg = _apply_spec(cfg, label_column, group_by, temporal_column, split_column, id_column)
    chosen = tuple(formats) if formats else ("json", "md", "html")
    with _progress(enabled=not quiet) as hook:
        result = audit_dataset(path, config=cfg, progress=hook, baseline_snapshot=baseline)
    written = write_reports(
        result.report,
        output,
        formats=chosen,
        plan=build_repair_plan(result.report.findings, root=str(path)),
    )
    if not quiet:
        _render(result, verbose=verbose)
    for file in written:
        console.print(f"[dim]{file}[/dim]")
    if save_snapshot:
        from .snapshots import build_snapshot, new_snapshot_name
        from .snapshots import save_snapshot as _save

        snapshot = build_snapshot(
            result.manifest, result.identity, new_snapshot_name(result.root, save_snapshot), result.report
        )
        console.print(f"[green]snapshot[/green] {_save(snapshot)}")
    raise typer.Exit(code=_exit_code(result, ci, strict, fail_on))


# ------------------------------------------------------------------ fingerprint
@app.command()
def fingerprint(
    path: Path = typer.Argument(Path()),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    fingerprint_mode: str = typer.Option("full", "--mode", help="metadata|full|sampled"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write the identity JSON here."),
    workers: int = typer.Option(0, "--workers"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Hash the dataset and print its identity - no rules, no verdict."""
    cfg = _load(path, config, None, fingerprint_mode, workers)
    result = scan(path, config=cfg)
    payload = {
        "dataset_id": result.identity.dataset_id,
        "manifest_hash": result.identity.manifest_hash,
        "config_hash": result.identity.config_hash,
        "fingerprint_mode": result.identity.fingerprint_mode.value,
        "num_samples": result.identity.num_samples,
        "split_sizes": result.identity.split_sizes,
        "class_counts": result.identity.class_counts,
        "samples": [
            {
                "sample_id": record.sample_id,
                "relative_path": record.relative_path,
                "split": record.split,
                "label": record.label,
                "sha256": record.sha256,
                "row_sha256": record.row_sha256,
            }
            for record in result.manifest.records
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        console.print(f"[green]wrote[/green] {output}")
    if not quiet:
        console.print(
            f"dataset [cyan]{result.identity.dataset_id}[/cyan] "
            f"manifest [cyan]{result.identity.manifest_hash[:16]}[/cyan] "
            f"({result.identity.num_samples:,} samples, {fingerprint_mode})"
        )
        if output is None:
            console.print(text[:2000] + ("\n… truncated" if len(text) > 2000 else ""))


# --------------------------------------------------------------------- snapshot
@app.command()
def snapshot(
    path: Optional[Path] = typer.Argument(None, help="Dataset to snapshot (omit with --list)."),
    name: Optional[str] = typer.Option(None, "--name", help="Snapshot name; defaults to a timestamp."),
    audit_first: bool = typer.Option(False, "--audit", help="Also run the rules and store the findings digest."),
    list_existing: bool = typer.Option(False, "--list", help="List stored snapshots."),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    directory: Optional[Path] = typer.Option(
        None, "--directory", help="Where snapshots live (default .dataset-doctor/snapshots)."
    ),
) -> None:
    """Store a lightweight fingerprint of the dataset to diff against later."""
    if list_existing:
        root = Path(path or ".").expanduser()
        found = list_snapshots(root, directory)
        if not found:
            console.print("[dim]no snapshots stored yet[/dim]")
            return
        for entry in found:
            console.print(f"{entry}")
        return
    if path is None:
        raise typer.BadParameter("a dataset path is required unless --list is given")
    cfg = _load(path, config, None, None, 0)
    stored, file = snapshot_dataset(path, name=name, config=cfg, audit=audit_first, directory=directory)
    summary = snapshot_summary(stored)
    console.print(f"[green]stored[/green] {file}")
    for line in summary:
        console.print(f"  {line}")


# ------------------------------------------------------------------------- diff
@app.command()
def diff(
    left: str = typer.Argument(..., help="Dataset directory or snapshot name/file."),
    right: Optional[str] = typer.Argument(None, help="Defaults to the current state of --left's dataset."),
    fingerprint_mode: Optional[str] = typer.Option(None, "--fingerprint", help="force the mode for both sides"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write the diff JSON here."),
    full: bool = typer.Option(False, "--full", help="List every changed sample instead of counts and previews."),
) -> None:
    """Compare two datasets, or a dataset against a stored snapshot."""
    target = right if right is not None else left
    result = diff_targets(left, target, fingerprint=fingerprint_mode)
    payload = result.model_dump(mode="json")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        console.print(f"[green]wrote[/green] {output}")
    if not result.comparable:
        console.print(f"[red]not comparable[/red] {result.not_comparable_reason}")
        raise typer.Exit(code=2)
    _render_diff(result, full=full)
    if result.summary.moved_between_splits and any(item.get("to") == "test" for item in result.moved_samples):
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


# ----------------------------------------------------------------------- report
@app.command()
def report(
    source: Path = typer.Argument(..., help="An existing report.json."),
    output: Path = typer.Option(Path(), "--output", "-o"),
    formats: Optional[list[str]] = typer.Option(None, "--format", "-f", help="json|md|html (repeatable)."),
) -> None:
    """Re-render Markdown/HTML from a stored ``report.json`` without re-reading data."""
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    # report.json carries two derived blocks that AuditReport itself does not own. The
    # repair plan is a pure function of the findings, so dropping it here rebuilds the
    # identical plan instead of trusting whatever was stored.
    payload.pop("repair_plan", None)
    payload.pop("diff", None)
    modelled = AuditReport.model_validate(payload)
    written = write_reports(modelled, output, formats=tuple(formats or ("md", "html")))
    for file in written:
        console.print(f"[green]wrote[/green] {file}")


# ------------------------------------------------------------------------ rules
@app.command()
def rules(
    rule_id: Optional[str] = typer.Argument(None, help="Show one rule in full."),
    doc: bool = typer.Option(False, "--doc", help="Print the docs path for each rule."),
) -> None:
    """List the DD001-DD021 rule registry: what is checked, at what cost."""
    if rule_id:
        rule = REGISTRY.get(rule_id.upper())
        if rule is None:
            raise typer.BadParameter(f"unknown rule '{rule_id}'")
        console.print_json(rule.model_dump_json())
        return
    table = Table(title=f"Dataset Doctor rules v{__version__}", show_lines=False)
    table.add_column("ID")
    table.add_column("Rule")
    table.add_column("Category")
    table.add_column("Default")
    table.add_column("Formal impact")
    table.add_column("Evidence")
    table.add_column("V0.1")
    for key, rule in REGISTRY.items():
        table.add_row(
            key,
            rule.name,
            rule.category.value,
            rule.default_severity.value,
            rule.formal_impact.value,
            rule.evidence_type.value,
            "[green]yes[/green]" if rule.implemented else "[dim]planned[/dim]",
        )
    console.print(table)
    if doc:
        for key, rule in REGISTRY.items():
            console.print(f"{key} -> {rule.doc_path}")
    console.print(
        "[dim]False-positive notes and remediation for each rule live in docs/rules/. "
        "Severity is policy, not code: see policies.<rule>.severity in dataset-doctor.yaml.[/dim]"
    )


# -------------------------------------------------------------------- split/demo
@app.command()
def split(
    path: Path = typer.Argument(..., help="Source dataset (never modified)."),
    output: Path = typer.Option(..., "--output", help="New directory for the split."),
    ratios: str = typer.Option(
        "train=0.8,val=0.1,test=0.1",
        "--ratios",
        help="name=value pairs, or bare numbers: 0.7,0.15,0.15 and 70/15/15 both work.",
    ),
    group_by: Optional[str] = typer.Option(None, "--group-by", help="Entity column, or a path regex for images."),
    stratify: Optional[str] = typer.Option(None, "--stratify", help="Label column to balance."),
    seed: int = typer.Option(42, "--seed"),
    dedupe: bool = typer.Option(False, "--dedupe", help="Drop exact duplicate rows first."),
) -> None:
    """Write a reproducible, group-safe split into a NEW directory."""
    parsed = _parse_ratios(ratios)
    result = split_dataset(
        SplitRequest(
            source=path,
            output=output,
            ratios=parsed,
            group_by=group_by,
            stratify=stratify,
            seed=seed,
            dedupe=dedupe,
        )
    )
    console.print(
        Panel(
            f"[bold]{result.strategy}[/bold]  seed={seed}  entities={result.units:,}  rows={result.rows:,}\n"
            + "  ".join(f"{name}={count:,}" for name, count in sorted(result.split_sizes.items()))
            + (f"\nduplicates removed: {result.duplicates_removed:,}" if dedupe else ""),
            title=f"split written to {result.output}",
            border_style="green" if not result.approximate else "yellow",
        )
    )
    for note in result.notes:
        console.print(f"[dim]- {note}[/dim]")
    console.print("[dim]Re-audit the result: dataset-doctor audit " + str(result.output) + "[/dim]")


@app.command()
def demo(
    output: Path = typer.Option(Path("dataset-doctor-demo"), "--output", "-o"),
    keep: bool = typer.Option(False, "--keep", help="Only generate; do not audit."),
    audit_image: bool = typer.Option(
        True, "--image/--no-image", help="Also generate the image fixture (needs Pillow)."
    ),
) -> None:
    """Generate a small dataset with known, deliberately planted problems and audit it."""
    from .demo import build_demo

    built = build_demo(output, images=audit_image)
    console.print(f"[green]generated[/green] {output}")
    for name, description in built.items():
        console.print(f"  [bold]{name}[/bold] - {description}")
    if keep:
        return
    for name, description in built.items():
        if description.startswith("skipped"):
            continue
        target = output / name
        console.print(f"\n[bold]=== {name} ===[/bold]")
        console.print(f"planted faults: {target / 'PLANTED_FAULTS.md'}")
        result = audit_dataset(target)
        _render(result, verbose=False)
        write_reports(result.report, output / "reports" / name)
    console.print(f"\nreports: {output / 'reports'}")


# ------------------------------------------------------------------------- help
@app.command()
def show(
    path: Path = typer.Argument(Path()),
    rule_id: Optional[str] = typer.Option(None, "--rule", "-r", help="Only this rule's findings."),
    severity: Optional[str] = typer.Option(None, "--severity", help="Minimum severity to print."),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    preset: Optional[str] = typer.Option(None, "--preset", "--policy"),
    fingerprint: Optional[str] = typer.Option(None, "--fingerprint"),
    workers: int = typer.Option(0, "--workers"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Audit and print the findings, but write no report files."""
    cfg = _load(path, config, preset, fingerprint, workers)
    with _progress(enabled=not quiet) as hook:
        result = audit_dataset(path, config=cfg, progress=hook)
    if rule_id or severity:
        _render_filtered(result, rule_id, severity)
        return
    _render(result, verbose=True)
    raise typer.Exit(code=result.exit_code())


def main() -> None:  # pragma: no cover - console_script wrapper
    try:
        app()
    except KeyboardInterrupt:
        # Ctrl+C is a supported way to stop. Reports are written after the audit finishes,
        # so an interrupted run leaves no half-written output behind - it only has to say
        # so without a traceback and with a code a CI system can distinguish from a failure.
        error_console.print("[yellow]interrupted[/yellow] no report was written")
        sys.exit(130)
    except DatasetDoctorError as exc:
        code = 2
        if isinstance(exc, SplitError):
            code = 2
        error_console.print(f"[red]error[/red] {exc}")
        sys.exit(code)
    except FileNotFoundError as exc:
        error_console.print(f"[red]error[/red] {exc}")
        sys.exit(2)
    except Exception as exc:
        error_console.print(f"[red]internal error[/red] {type(exc).__name__}: {exc}")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            raise exc
        sys.exit(3)


# --------------------------------------------------------------------- internals
def _load(
    path: Path,
    config: Path | None,
    preset: str | None,
    fingerprint_mode: str | None,
    workers: int,
    dataset_type: str | None = None,
    sample: float | None = None,
    no_cache: bool = False,
) -> Config:
    cfg = load_config(Path(path), config, preset, fingerprint_mode, workers or None)
    if dataset_type:
        try:
            cfg.dataset.type = DatasetType(dataset_type)
        except ValueError as exc:
            raise ConfigError(f"--type must be tabular or image, got '{dataset_type}'") from exc
    if sample is not None:
        cfg.fingerprint = FingerprintMode.SAMPLED
        cfg.sampling.enabled = True
        cfg.sampling.fraction = sample
    if no_cache:
        cfg.performance.cache = False
    return cfg


def _apply_spec(
    cfg: Config,
    label_column: str | None,
    group_by: Optional[list[str]],
    temporal_column: str | None,
    split_column: str | None,
    id_column: Optional[list[str]],
) -> Config:
    if label_column:
        cfg.labels.column = label_column
        cfg.labels.source = "column"
    if group_by:
        cfg.groups.columns = list(dict.fromkeys([*cfg.groups.columns, *group_by]))
    if temporal_column:
        cfg.temporal.column = temporal_column
    if split_column:
        cfg.temporal.split_column = split_column
    if id_column:
        cfg.id_columns = list(dict.fromkeys([*cfg.id_columns, *id_column]))
    return cfg


def _progress(enabled: bool = True) -> AbstractContextManager[Any]:
    """Yield a ``progress(split, done, total)`` hook, or ``None`` when quiet."""
    if not enabled:

        @contextmanager
        def _quiet() -> Iterator[Any]:
            yield None

        return _quiet()

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    )
    tasks: dict[str, Any] = {}

    def hook(split: str, done: int, total: int) -> None:
        key = f"scan:{split}"
        task = tasks.get(key)
        if task is None:
            task = progress.add_task(f"hashing {split}", total=total)
            tasks[key] = task
        progress.update(task, completed=done, total=max(total, done))

    @contextmanager
    def _live() -> Iterator[Any]:
        with progress:
            yield hook

    return _live()


def _render(result: AuditResult, verbose: bool = False) -> None:
    report_model = result.report
    identity = report_model.identity
    style = _VERDICT_STYLE.get(report_model.eval_safety, "white")
    counts = report_model.summary.by_severity
    badge = "  ".join(
        f"[{_SEVERITY_STYLE[sev]}]{counts.get(sev.value, 0)} {sev.value}[/]"
        for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
    )
    console.print(
        Panel(
            f"[{style}]{report_model.eval_safety.value}[/]  [dim]{identity.num_samples:,} samples / "
            f"{len(report_model.rule_outcomes)} rules[/dim]\n{badge}",
            title=f"{identity.root_path}",
            border_style=style,
        )
    )
    for reason in report_model.eval_safety_reasons[:8]:
        console.print(f"  [dim]- {reason}[/dim]")
    shown = [
        finding
        for finding in sorted(report_model.findings, key=lambda item: (-item.severity.rank, item.finding_id))
        if finding.severity is not Severity.INFO or verbose
    ]
    for finding in shown:
        where = finding.source_split or (finding.location.columns[0] if finding.location.columns else "dataset")
        console.print(
            f"[{_SEVERITY_STYLE[finding.severity]}]{finding.severity.value:<8}[/] "
            f"[bold]{finding.finding_id}[/] {finding.title} "
            f"[dim]({finding.affected_count:,} samples, {where})[/dim]"
        )
    if not verbose:
        return
    table = Table(show_header=True, header_style="dim")
    for column in ("Rule", "Name", "Status", "Findings", "Severity", "Note"):
        table.add_column(column, overflow="fold")
    for outcome in report_model.rule_outcomes:
        rule = REGISTRY.get(outcome.rule_id)
        table.add_row(
            outcome.rule_id,
            rule.name if rule else "-",
            f"[{_STATUS_STYLE.get(outcome.status, 'white')}]{outcome.status.value}[/]",
            str(outcome.finding_count),
            outcome.highest_severity.value if outcome.highest_severity else "-",
            (outcome.skip_reason or outcome.suppression_reason or "")[:90],
        )
    console.print(table)


def _render_filtered(result: AuditResult, rule_id: str | None, severity: str | None) -> None:
    threshold = Severity[severity.upper()] if severity else Severity.INFO
    for finding in result.report.findings:
        if rule_id and finding.rule_id != rule_id.upper():
            continue
        if finding.severity.rank < threshold.rank:
            continue
        console.print(
            f"[bold]{finding.finding_id}[/] {finding.title}\n"
            f"  {finding.description}\n  [dim]{finding.why_it_matters}[/dim]\n"
            f"  evidence: {json.dumps(finding.evidence, sort_keys=True, default=str)[:400]}\n"
            f"  [green]{finding.recommended_action}[/green]"
        )


def _render_diff(diff_result: Any, full: bool = False) -> None:
    summary = diff_result.summary.model_dump()
    console.print(
        f"[bold]{diff_result.left}[/] -> [bold]{diff_result.right}[/]  "
        f"[dim]{diff_result.left_identity.num_samples if diff_result.left_identity else '?'} -> "
        f"{diff_result.right_identity.num_samples if diff_result.right_identity else '?'} samples[/dim]"
    )
    for key in (
        "added",
        "removed",
        "modified",
        "moved_between_splits",
        "changed_labels",
        "new_findings",
        "resolved_findings",
        "new_leakage",
        "resolved_leakage",
    ):
        value = summary.get(key, 0)
        style = "red" if value and key.startswith(("new", "moved")) else "dim"
        console.print(f"  {key:<22} [{style}]{value:,}[/]")
    change = diff_result.eval_safety_change
    if change:
        console.print(f"  verdict                {change.get('left')} -> {change.get('right')}")
    if full:
        for group in (diff_result.added_samples, diff_result.removed_samples):
            if group:
                console.print(f"  [dim]{len(group):,} sample ids: {', '.join(group[:20])}…[/dim]")
    else:
        for item in diff_result.moved_samples[:5]:
            console.print(f"  [yellow]moved[/yellow] {item.get('sample_id')}: {item.get('from')} -> {item.get('to')}")


def _exit_code(result: AuditResult, ci: bool, strict: bool, fail_on: str | None) -> int:
    if fail_on == "never":
        return 0
    if fail_on:
        try:
            threshold = Severity[fail_on.upper()]
        except KeyError as exc:
            raise typer.BadParameter(
                f"--fail-on must be one of never|low|medium|high|critical (got {fail_on})"
            ) from exc
        return 1 if any(f.severity.rank >= threshold.rank for f in result.report.findings) else 0
    return result.exit_code(ci=ci, strict=strict)


_DEFAULT_SPLIT_NAMES = {2: ("train", "test"), 3: ("train", "val", "test")}


def _parse_ratios(text: str) -> dict[str, float]:
    """Read ``train=0.7,test=0.3``, ``0.7,0.3`` or ``70/15/15``.

    The bare forms are divided by their own sum, so 70/15/15 means the same as
    0.7/0.15/0.15. Naming and validation of the result stays with the splitting layer.
    """
    chunks = [chunk for chunk in re.split(r"[/,]", text) if chunk.strip()]
    if chunks and all("=" in chunk for chunk in chunks):
        out: dict[str, float] = {}
        for chunk in chunks:
            name, _, value = chunk.partition("=")
            try:
                out[name.strip().lower()] = float(value)
            except ValueError as exc:
                raise typer.BadParameter(f"--ratios expects name=value pairs, got '{chunk}'") from exc
        return out
    try:
        numbers = [float(chunk) for chunk in chunks]
    except ValueError as exc:
        raise typer.BadParameter(f"cannot read --ratios '{text}'; use name=value pairs or 2-3 numbers") from exc
    names = _DEFAULT_SPLIT_NAMES.get(len(numbers))
    if names is None:
        raise typer.BadParameter("--ratios needs 2 or 3 numbers, or name=value pairs")
    total = sum(numbers)
    if total <= 0:
        raise typer.BadParameter("--ratios must add up to more than zero")
    return dict(zip(names, (value / total for value in numbers), strict=True))


def _scan_dict(result: Any) -> dict[str, Any]:
    return {
        "root": str(result.root),
        "dataset_id": result.identity.dataset_id,
        "manifest_hash": result.identity.manifest_hash,
        "fingerprint_mode": result.manifest.mode.value,
        "num_samples": result.identity.num_samples,
        "split_sizes": result.identity.split_sizes,
        "schema": result.identity.schema,
        "notes": result.spec.inference_notes,
    }


__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
