"""TEST 22 / TEST 23: the tool must do its whole job with no API key, no network and no GPU.

V0.1's promise is local-first: an audit is deterministic file analysis, so a missing
credential or an absent graphics card cannot degrade a verdict. Two kinds of evidence
are produced here - a static scan of what the package is even capable of importing, and
a live audit run with the network syscalls and the GPU environment variable taken away.
Numbers reported in the docs come from the second kind, not from this file.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import TABULAR_COLUMNS, row, write_rows

from dataset_doctor import audit_dataset

PACKAGE = Path(__file__).resolve().parents[1] / "dataset_doctor"

#: Anything that could move bytes off the machine, train a model, or call a hosted model.
FORBIDDEN_ROOTS = {
    "requests",
    "urllib",
    "urllib2",
    "http",
    "httpx",
    "httplib2",
    "socket",
    "ssl",
    "ftplib",
    "smtplib",
    "telnetlib",
    "websocket",
    "wsgiref",
    "xmlrpc",
    "boto3",
    "botocore",
    "azure",
    "google",
    "openai",
    "anthropic",
    "cohere",
    "mistralai",
    "huggingface_hub",
    "transformers",
    "diffusers",
    "datasets",
    "gradio",
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "keras",
    "jax",
    "flax",
    "cupy",
    "triton",
    "onnxruntime",
    "accelerate",
    "bitsandbytes",
    "subprocess",
    "multiprocessing",
    "threading",
    "asyncio",
    "mmap",
}

#: Only what would need a GPU or a hosted model. pandas drags ``socket`` and ``asyncio``
#: in transitively, so the runtime probe uses this narrower set while the source scan
#: above uses the full one.
GPU_OR_LLM_ROOTS = FORBIDDEN_ROOTS - {
    "socket",
    "ssl",
    "http",
    "httpx",
    "httplib2",
    "urllib",
    "urllib2",
    "websocket",
    "wsgiref",
    "xmlrpc",
    "ftplib",
    "smtplib",
    "telnetlib",
    "asyncio",
    "threading",
    "mmap",
    "multiprocessing",
    "subprocess",
    "azure",
    "botocore",
    "boto3",
    "google",
}


def _requirement_name(spec: str) -> str:
    """``"pillow>=10"`` / ``"imagehash[binning]>=4"`` -> the distribution name."""
    for separator in ("[", ">", "<", "=", "!", "~", ";", " "):
        spec = spec.split(separator)[0]
    return spec.strip().lower()


def _imported_names() -> dict[str, set[str]]:
    """Map every module in the package to the top-level names it imports, static or lazy."""
    found: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        found[path.relative_to(PACKAGE.parent).as_posix()] = names
    return found


def test_test22_no_network_library_or_model_framework_is_imported_anywhere() -> None:
    """A grep-level guarantee: the dependency the spec forbids is not reachable at all.

    Lazy ``import x`` inside a function counts, which is why this is an AST scan and not a
    check of ``sys.modules``.
    """
    imported = _imported_names()
    assert imported, f"no package found at {PACKAGE}"

    bad = {module: sorted(names & FORBIDDEN_ROOTS) for module, names in imported.items() if names & FORBIDDEN_ROOTS}
    assert bad == {}, f"forbidden imports present: {bad}"


def test_the_package_reads_nothing_from_the_environment() -> None:
    """No API key, no token, no proxy variable: the audit cannot be silently reconfigured."""
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*.py"))
    assert "os.environ" not in text
    assert "getenv" not in text


def _manifest_dataset(root: Path) -> Path:
    """A small but genuinely contaminated table: 6 exact copies plus shared entities."""
    root.mkdir(parents=True)
    train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)]
    test = [dict(train[k]) for k in range(6)]  # byte-identical rows, leaked into the eval split
    test += [row(f"t{i:03d}", f"q{i // 4:02d}", index=100 + i) for i in range(6, 20)]
    write_rows(root / "train.csv", train, TABULAR_COLUMNS)
    write_rows(root / "test.csv", test, TABULAR_COLUMNS)
    (root / "dataset-doctor.yaml").write_text(
        "dataset:\n  type: tabular\nlabels:\n  column: target\n"
        "groups:\n  columns: [patient_id]\nid_columns: [record_id]\npolicies: {}\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope="module")
def leaky_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _manifest_dataset(tmp_path_factory.mktemp("standalone") / "leaky")


def test_test22_the_full_audit_still_completes_with_the_network_switched_off(
    leaky_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavioural proof, not a grep: every syscall that could phone home raises on use."""

    def refused(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the audit tried to open a network connection")

    monkeypatch.setattr(socket, "socket", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(socket, "getaddrinfo", refused)
    for name in list(os.environ):
        if any(token in name.upper() for token in ("API_KEY", "TOKEN", "SECRET", "PROXY")):
            monkeypatch.delenv(name, raising=False)

    result = audit_dataset(leaky_root)

    assert "DD003" in [finding.rule_id for finding in result.findings]
    assert result.report.eval_safety.value == "FORMAL_EVAL_INVALID"


def test_test23_an_audit_with_no_gpu_and_a_stripped_environment_matches_the_local_one(
    leaky_root: Path, tmp_path: Path
) -> None:
    """Run the real CLI as a child process that cannot see a GPU and has no credentials."""
    expected = audit_dataset(leaky_root)
    outdir = tmp_path / "out"

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "PYTHONPATH": str(PACKAGE.parent),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "CUDA_VISIBLE_DEVICES": "",
        "HF_HUB_OFFLINE": "1",
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
    }
    command = [
        sys.executable,
        "-m",
        "dataset_doctor.cli",
        "audit",
        str(leaky_root),
        "--output",
        str(outdir),
        "--format",
        "json",
        "--quiet",
    ]
    completed = subprocess.run(command, cwd=str(PACKAGE.parent), env=environment, capture_output=True, timeout=300)

    assert completed.returncode == 1, completed.stdout.decode("utf-8", "replace")[-800:]
    payload = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    assert [finding["rule_id"] for finding in payload["findings"]] == [finding.rule_id for finding in expected.findings]
    assert payload["eval_safety"] == expected.report.eval_safety.value
    assert payload["identity"]["num_samples"] == expected.identity.num_samples


def test_test23_the_child_process_imports_no_gpu_framework(tmp_path: Path, leaky_root: Path) -> None:
    """A leaked ``import torch`` would show up here even if the source scan missed a path."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys, json\n"
        "from dataset_doctor import audit_dataset\n"
        "result = audit_dataset(sys.argv[1])\n"
        f"heavy = {frozenset(GPU_OR_LLM_ROOTS)!r}\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in heavy)\n"
        "print(json.dumps({'modules': loaded, 'findings': len(result.findings)}))\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(leaky_root)],
        cwd=str(PACKAGE.parent),
        capture_output=True,
        timeout=300,
        env={
            **os.environ,
            "PYTHONPATH": str(PACKAGE.parent),
            "CUDA_VISIBLE_DEVICES": "",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")[-800:]
    probe = json.loads(completed.stdout.decode("utf-8"))
    assert probe["modules"] == [], "an audit imported a GPU or hosted-model framework"
    assert probe["findings"] > 0, "the probe audited nothing, so its import list proves nothing"


def test_runtime_dependencies_stay_inside_the_local_only_set() -> None:
    """The install must stay possible on a machine with no CUDA toolkit and no token."""
    pyproject = tomllib.loads((PACKAGE.parent / "pyproject.toml").read_text(encoding="utf-8"))
    required = {
        _requirement_name(item)
        for item in pyproject["project"]["dependencies"]
        if _requirement_name(item) not in {"python"}
    }

    allowed = {
        "numpy",
        "pandas",
        "pydantic",
        "pyyaml",
        "typer",
        "rich",
        "pillow",
        "scipy",
        "imagehash",
        "openpyxl",
        "pyarrow",
    }
    assert required <= allowed, f"new runtime dependency needs a local-first review: {required - allowed}"
