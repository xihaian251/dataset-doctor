"""Streaming content hashes, a cache, and perceptual hashes.

Two hard constraints from the spec: never load a whole file into memory
(section 84 -> fixed-size streaming), and never recompute a hash for a file that
has not changed (section 141 -> cache keyed on path + size + mtime, section 142).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

DEFAULT_CHUNK = 1024 * 1024
CACHE_VERSION = "1"


def sha256_file(path: Path, chunk_size: int = DEFAULT_CHUNK) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stable_sample_id(*parts: object) -> str:
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def file_cache_key(path: Path) -> str:
    stat = path.stat()
    return f"{os.path.normcase(str(path.resolve()))}|{stat.st_size}|{int(stat.st_mtime)}"


class HashCache:
    """Append-friendly JSONL cache. Corruption is tolerated: a bad line is skipped."""

    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self.entries: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.broken_lines = 0
        if enabled and path.is_file():
            self._load()

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        self.entries[row["key"]] = row
                    except (json.JSONDecodeError, KeyError):
                        self.broken_lines += 1
        except OSError:
            self.entries = {}

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        found = self.entries.get(key)
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self.enabled:
            self.entries[key] = value

    def save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"cache_version": CACHE_VERSION}) + "\n")
            for row in self.entries.values():
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self.entries),
            "hits": self.hits,
            "misses": self.misses,
            "broken_lines": self.broken_lines,
        }


def _hash_one(path: Path, chunk_size: int, cache: HashCache) -> tuple[str, str]:
    key = file_cache_key(path)
    cached = cache.get(key)
    if cached and cached.get("sha256"):
        return str(path), str(cached["sha256"])
    digest = sha256_file(path, chunk_size)
    cache.put(
        key,
        {"path": str(path).replace("\\", "/"), "size": path.stat().st_size, "sha256": digest},
    )
    return str(path), digest


def hash_files(
    paths: Sequence[Path],
    chunk_size: int = DEFAULT_CHUNK,
    workers: int = 1,
    cache: HashCache | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    """Map ``str(path) -> sha256``. Threads (not processes): this workload is IO bound."""
    cache = cache or HashCache(Path(os.devnull), enabled=False)
    results: dict[str, str] = {}
    total = len(paths)
    if workers <= 1:
        for done, path in enumerate(paths, start=1):
            key, value = _hash_one(path, chunk_size, cache)
            results[key] = value
            if progress:
                progress(done, total)
        return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (key, value) in enumerate(pool.map(lambda p: _hash_one(p, chunk_size, cache), paths), start=1):
            results[key] = value
            if progress:
                progress(done, total)
    return results


def open_image(path: Path) -> Any | None:
    from PIL import Image, ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(path) as handle:
            handle.load()
            return handle.copy()
    except Exception:
        return None


def _phash_one(path: Path) -> tuple[str, str | None]:
    image = open_image(path)
    if image is None:
        return str(path), None
    try:
        import imagehash

        return str(path), str(imagehash.phash(image))
    except Exception:
        return str(path), None


def perceptual_hashes(
    paths: Iterable[Path],
    workers: int = 1,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, str | None]:
    """``imagehash`` is an optional extra; absence degrades to no near-dup coverage."""
    items = list(paths)
    total = len(items)
    results: dict[str, str | None] = {}
    if workers <= 1:
        for done, path in enumerate(items, start=1):
            key, value = _phash_one(path)
            results[key] = value
            if progress:
                progress(done, total)
        return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (key, value) in enumerate(pool.map(_phash_one, items), start=1):
            results[key] = value
            if progress:
                progress(done, total)
    return results


def imagehash_available() -> bool:
    try:
        import imagehash  # noqa: F401
    except ImportError:
        return False
    return True


def hex_to_bits(hex_hash: str) -> int:
    return int(hex_hash, 16)


def hamming_hex(left: str, right: str) -> int:
    """Hamming distance between two hex-encoded bit strings of equal length."""
    if len(left) != len(right):
        raise ValueError(f"Hash lengths differ: {len(left)} vs {len(right)}")
    return bin(int(left, 16) ^ int(right, 16)).count("1")
