"""Image-folder adapter.

One decode pass per file (spec sections 84/85): integrity check, dimension/format
stats and the perceptual hash are collected together, because opening a JPEG three
times in three different detectors is the fastest way to make a 10k-image audit
take three times as long.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from ..discovery import IMAGE_SUFFIXES, is_ignored
from ..hashing import file_cache_key, open_image, sha256_file
from ..models import DatasetType, SampleRecord, SplitSpec
from .base import DatasetAdapter, ProgressFn

NULL_LABELS = {"", "unknown", "none", "null", "unlabeled", "unmapped", "-"}


class ImageFolderAdapter(DatasetAdapter):
    dataset_type: ClassVar[DatasetType] = DatasetType.IMAGE
    capabilities: ClassVar[frozenset[str]] = frozenset({"images", "files"})

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.inspected: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []
        self.hash_only = False

    # ----------------------------------------------------------------- walking
    def files_for(self, split: SplitSpec) -> list[Path]:
        path = Path(split.path)
        if not path.is_absolute():
            path = self.root / path
        if path.is_file():
            return [path]
        if not path.is_dir():
            self.skipped.append({"path": self.relative(path), "reason": "split path does not exist"})
            return []
        out: list[Path] = []
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(path)
            if any(is_ignored(part, self.config) for part in relative.parts):
                continue
            if candidate.suffix.lower() in IMAGE_SUFFIXES:
                out.append(candidate)
            else:
                self.skipped.append(
                    {
                        "path": self.relative(candidate),
                        "reason": f"not a supported image extension ({candidate.suffix or 'none'})",
                    }
                )
        return out

    # ----------------------------------------------------------------- samples
    def samples(self, progress: ProgressFn = None) -> list[SampleRecord]:
        settings = self.config.policies.item("near_duplicate").extra_settings()
        want_phash = bool(
            self.config.policies.item("near_duplicate").enabled and settings.get("method", "phash") != "none"
        )
        records: list[SampleRecord] = []
        for split in self.splits:
            files = self.files_for(split)
            for done, file in enumerate(files, start=1):
                records.append(self._record(file, split, want_phash))
                if progress:
                    progress(split.name, done, len(files))
        return self.require_non_empty(records)

    def _record(self, file: Path, split: SplitSpec, want_phash: bool) -> SampleRecord:
        stat = file.stat()
        rel = self.relative(file)
        digest = self._cached_sha(file) if self._wants_content_hash else None
        inspection = self._inspect(file, want_phash)
        self.inspected.append({"relative_path": rel, "split": split.name, **inspection})
        label = self.label_of(file, split)
        if label is not None and label.lower() in NULL_LABELS:
            label = None
        metadata = {k: v for k, v in inspection.items() if v is not None}
        return SampleRecord(
            sample_id=rel,
            relative_path=rel,
            split=split.name,
            label=label,
            size=stat.st_size,
            mtime=stat.st_mtime,
            sha256=digest,
            phash=inspection.get("phash"),
            metadata=metadata,
        )

    @property
    def _wants_content_hash(self) -> bool:
        return self.config.fingerprint.value in {"full", "sampled"}

    def _cached_sha(self, file: Path) -> str:
        if self.cache is None:
            return sha256_file(file, self.config.performance.chunk_size)
        key = file_cache_key(file)
        found = self.cache.get(key)
        if found and found.get("sha256"):
            return str(found["sha256"])
        digest = sha256_file(file, self.config.performance.chunk_size)
        self.cache.put(key, {"path": self.relative(file), "size": file.stat().st_size, "sha256": digest})
        return digest

    # --------------------------------------------------------------- inspection
    def _inspect(self, file: Path, want_phash: bool) -> dict[str, Any]:
        if file.stat().st_size == 0:
            return {"corrupt": True, "error": "zero-byte file"}
        if self.config.fingerprint.value == "metadata":
            # Deliberately does not decode pixels: cheap, but integrity and property
            # rules cannot answer and must return INCONCLUSIVE.
            return {"inspected": False}
        image = open_image(file)
        if image is None:
            return {"corrupt": True, "error": "unreadable or truncated image data"}
        result: dict[str, Any] = {"corrupt": False, "error": None}
        try:
            result["width"], result["height"] = image.size
            result["format"] = (image.format or "").lower() or None
            result["mode"] = image.mode
            result["channels"] = channel_count(image.mode)
            brightness, contrast = luminance_stats(image)
            result["brightness"] = brightness
            result["contrast"] = contrast
            if want_phash:
                result["phash"] = self._phash(file)
        finally:
            image.close()
        return result

    def _phash(self, file: Path) -> str | None:
        try:
            import imagehash
            from PIL import Image
        except ImportError:
            self.note("imagehash is not installed: near-duplicate detection unavailable")
            return None
        try:
            with Image.open(file) as handle:
                return str(imagehash.phash(handle))
        except Exception:
            return None


def channel_count(mode: str) -> int:
    return {"L": 1, "LA": 2, "1": 1, "P": 1, "RGB": 3, "RGBA": 4, "CMYK": 4}.get(mode, 3)


def luminance_stats(image: Any) -> tuple[float | None, float | None]:
    """Mean and std of the luma channel, from the histogram (no numpy needed)."""
    try:
        gray = image.convert("L")
        hist = gray.histogram()
        total = sum(hist)
        if not total:
            return None, None
        mean = sum(index * count for index, count in enumerate(hist)) / total
        variance = sum(((index - mean) ** 2) * count for index, count in enumerate(hist)) / total
        return round(mean, 2), round(variance**0.5, 2)
    except Exception:
        return None, None
