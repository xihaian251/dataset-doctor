"""DD003 exact duplicates and DD004 near duplicates.

Exact duplicates are a deterministic fact: identical content, therefore identical
sample. The only judgement is where they sit - inside one split (redundancy that
skews sample weights) or across splits (a leak). Those two are reported as different
findings with different formal impact, because conflating them is how "we have
duplicates" turns into an unfalsifiable accusation (spec sections 20 and 25).

Near duplicates use a bit-band candidate generator instead of all-pairs comparison:
for Hamming threshold t, two 64-bit hashes within distance t must agree exactly on at
least one of t+1 disjoint bit bands, so band collisions are a superset of the matches
(spec section 87 - no O(N^2) sweep).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..config import Config
from ..hashing import hamming_hex
from ..models import (
    AuditStatus,
    Category,
    Confidence,
    EvidenceType,
    FormalImpact,
    SampleRecord,
    Severity,
    SplitRole,
)
from .context import AuditContext, InsufficientEvidence, NotApplicable, build_finding


def detect_exact_duplicates(ctx: AuditContext) -> list[Any]:
    """Group samples by content hash and classify by split placement."""
    ctx.needs_content_hashes()
    hashed = [
        record
        for record in ctx.records
        if (record.sha256 or record.row_sha256) and record.metadata.get("hash_sampled", True)
    ]
    if not hashed:
        raise InsufficientEvidence(
            "No content hashes available, so duplication cannot be measured. Re-run with `--fingerprint full`."
        )
    key = "sha256" if ctx.dataset_type.value == "image" else "row_sha256"
    groups: dict[str, list[SampleRecord]] = defaultdict(list)
    for record in hashed:
        digest = getattr(record, key)
        if digest:
            groups[digest].append(record)
    duplicated = {digest: members for digest, members in groups.items() if len(members) > 1}
    if not duplicated:
        return []

    cross = {d: m for d, m in duplicated.items() if len({r.split for r in m}) > 1}
    within = {d: m for d, m in duplicated.items() if len({r.split for r in m}) == 1}
    findings: list[Any] = []
    sequence = 1

    if cross:
        by_pair: dict[tuple[str, str], list[tuple[str, list[SampleRecord]]]] = defaultdict(list)
        for digest, members in cross.items():
            for pair in _split_pairs(sorted({r.split for r in members})):
                by_pair[pair].append((digest, members))
        ordered = sorted(
            by_pair.items(),
            key=lambda item: (_pair_priority(ctx, item[0][0], item[0][1]), -len(item[1])),
        )
        for (split_a, split_b), entries in ordered:
            members = [record for _, group in entries for record in group]
            count = len({record.sample_id for record in members})
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD003",
                    sequence=sequence,
                    title=f"Cross-split exact duplicates: {split_a} / {split_b}",
                    category=Category.DUPLICATE,
                    severity=_cross_severity(ctx, split_a, split_b),
                    status=AuditStatus.FAIL,
                    evidence_type=EvidenceType.DETERMINISTIC,
                    confidence=Confidence.HIGH,
                    formal_impact=FormalImpact.BLOCKING,
                    affected=[record.sample_id for record in members],
                    affected_count=count,
                    source_split=split_a,
                    target_split=split_b,
                    description=(
                        f"{len(entries)} identical content group(s) span {split_a} and {split_b}; "
                        f"{count} samples are involved."
                    ),
                    why_it_matters=(
                        f"Identical content sits on both sides of the {split_a}/{split_b} boundary, so "
                        f"whatever is held out for scoring was also fitted. The reported number measures "
                        "memorisation as well as generalisation, and no downstream hyperparameter choice "
                        "can recover its meaning. This is the one duplicate class that invalidates a metric."
                    ),
                    evidence={
                        "duplicate_groups": len(entries),
                        "key": key,
                        "groups": [
                            {
                                key: digest,
                                "members": [
                                    {"sample_id": r.sample_id, "split": r.split, "label": r.label} for r in group[:10]
                                ],
                            }
                            for digest, group in sorted(entries, key=lambda item: -len(item[1]))[:20]
                        ],
                    },
                    metadata={"scope": "cross_split"},
                )
            )
            sequence += 1

    if within:
        by_split: dict[str, list[tuple[str, list[SampleRecord]]]] = defaultdict(list)
        for digest, members in within.items():
            by_split[members[0].split].append((digest, members))
        for split, entries in sorted(by_split.items(), key=lambda item: -len(item[1])):
            members = [record for _, group in entries for record in group]
            redundant = sum(len(group) - 1 for _, group in entries)
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD003",
                    sequence=sequence,
                    title=f"Within-split exact duplicates in '{split}'",
                    category=Category.DUPLICATE,
                    severity=Severity.MEDIUM,
                    status=AuditStatus.WARNING,
                    evidence_type=EvidenceType.DETERMINISTIC,
                    confidence=Confidence.HIGH,
                    formal_impact=FormalImpact.POTENTIAL,
                    affected=[record.sample_id for record in members],
                    affected_count=len(members),
                    source_split=split,
                    description=(
                        f"{len(entries)} identical content group(s) repeat inside {split} "
                        f"({redundant} redundant copies)."
                    ),
                    why_it_matters=(
                        "Duplicates do not leak across the evaluation boundary here, but they overweight "
                        "the duplicated material in the loss and shrink the effective sample size."
                    ),
                    evidence={
                        "duplicate_groups": len(entries),
                        "redundant_copies": redundant,
                        "key": key,
                        "groups": [
                            {
                                key: digest,
                                "members": [r.sample_id for r in group[:10]],
                            }
                            for digest, group in sorted(entries, key=lambda item: -len(item[1]))[:20]
                        ],
                    },
                    metadata={"scope": "within_split"},
                )
            )
            sequence += 1
    return findings


def _cross_severity(ctx: AuditContext, split_a: str, split_b: str) -> Severity:
    roles = {ctx.role_of(split_a), ctx.role_of(split_b)}
    if SplitRole.TRAIN in roles and SplitRole.TEST in roles:
        return Severity.CRITICAL
    if SplitRole.TEST in roles or SplitRole.TRAIN in roles:
        return Severity.HIGH
    return Severity.HIGH


def _split_pairs(splits: list[str]) -> list[tuple[str, str]]:
    return [(splits[i], splits[j]) for i in range(len(splits)) for j in range(i + 1, len(splits))]


def _pair_priority(ctx: AuditContext, a: str, b: str) -> int:
    roles = {ctx.role_of(a), ctx.role_of(b)}
    if roles == {SplitRole.TRAIN, SplitRole.TEST}:
        return 0
    if SplitRole.TEST in roles:
        return 1
    return 2


def _same_content(a: SampleRecord, b: SampleRecord) -> bool:
    left = a.sha256 or a.row_sha256
    right = b.sha256 or b.row_sha256
    return left is not None and left == right


# ------------------------------------------------------------------ near duplicate
def detect_near_duplicates(ctx: AuditContext) -> list[Any]:
    if not ctx.adapter.supports("images"):
        raise NotApplicable("near-duplicate detection is defined for image datasets", "UNSUPPORTED")
    item = ctx.config.policies.item("near_duplicate")
    if not item.enabled:
        raise NotApplicable("policy near_duplicate.enabled = false", "NOT_RUN")
    settings = item.extra_settings()
    threshold = int(settings.get("hamming_threshold", 6))
    method = str(settings.get("method", "phash"))
    if method != "phash":
        raise NotApplicable(f"method '{method}' is not implemented in V0.1 (only phash)", "UNSUPPORTED")
    try:
        import imagehash  # noqa: F401
    except ImportError:
        raise InsufficientEvidence(
            "imagehash is not installed; near-duplicate detection needs `pip install imagehash` "
            "(or the `image` extra). Rule DD004 did not run - this is not a PASS."
        ) from None

    signed = [record for record in ctx.records if record.phash]
    if len(signed) < 2:
        raise InsufficientEvidence("Fewer than two images carry a perceptual hash, so similarity cannot be measured.")
    if len(signed) < len(ctx.records):
        ctx.adapter.note(
            f"{len(ctx.records) - len(signed)} sample(s) had no pHash (corrupt or skipped) and are "
            "outside DD004 coverage"
        )

    max_bucket = int(settings.get("max_bucket_size", 200))
    pairs, buckets_truncated = _band_candidates(signed, threshold, max_bucket)
    matches = [(a, b, distance) for a, b, distance in pairs if distance <= threshold]
    # Byte-identical pairs are DD003's finding; repeating them here would price one fault
    # twice at two different severities.
    exact_pairs = [triplet for triplet in matches if _same_content(triplet[0], triplet[1])]
    matches = [triplet for triplet in matches if not _same_content(triplet[0], triplet[1])]
    cross = [(a, b, d) for a, b, d in matches if a.split != b.split]
    within = [(a, b, d) for a, b, d in matches if a.split == b.split]
    findings: list[Any] = []
    sequence = 1

    limitations = [
        f"pHash is a 64-bit heuristic: hamming_threshold={threshold} was set by policy, not derived from this dataset.",
        "Perceptual hashes do not survive crops, rotations, EXIF orientation or heavy recompression, "
        "so a clean report here does not prove absence of visual duplication.",
    ]
    if exact_pairs:
        limitations.append(
            f"{len(exact_pairs)} pair(s) with identical content hashes were left to DD003 instead of "
            "being counted a second time here."
        )

    if cross:
        for split_a, split_b, group in _group_by_pair(ctx, cross):
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD004",
                    sequence=sequence,
                    title=f"Near-duplicate leakage candidates: {split_a} / {split_b}",
                    category=Category.DUPLICATE,
                    severity=Severity.HIGH,
                    status=AuditStatus.WARNING,
                    evidence_type=EvidenceType.HEURISTIC,
                    confidence=Confidence.MEDIUM,
                    formal_impact=FormalImpact.POTENTIAL,
                    affected=[r.sample_id for a, b, _ in group for r in (a, b)],
                    source_split=split_a,
                    target_split=split_b,
                    description=(
                        f"{len(group)} visually near-identical image pair(s) cross the {split_a}/{split_b} "
                        f"boundary at Hamming distance <= {threshold}."
                    ),
                    why_it_matters=(
                        "A leakage *candidate*, not a confirmed leak: if these are the same physical object "
                        "photographed twice, the evaluation is partly measuring recall of the training images."
                    ),
                    evidence={
                        "method": "phash",
                        "hamming_threshold": threshold,
                        "pairs": [
                            {
                                "image_a": a.sample_id,
                                "image_b": b.sample_id,
                                "hamming_distance": d,
                                "phash_a": a.phash,
                                "phash_b": b.phash,
                                "split_a": a.split,
                                "split_b": b.split,
                                "label_a": a.label,
                                "label_b": b.label,
                                "size_a": f"{a.metadata.get('width')}x{a.metadata.get('height')}",
                                "size_b": f"{b.metadata.get('width')}x{b.metadata.get('height')}",
                            }
                            for a, b, d in sorted(group, key=lambda item: item[2])[:20]
                        ],
                    },
                    limitations=limitations,
                    metadata={"scope": "cross_split"},
                )
            )
            sequence += 1

    if within:
        pairs_by_split: dict[str, list] = defaultdict(list)
        for a, b, d in within:
            pairs_by_split[a.split].append((a, b, d))
        for split, group in sorted(pairs_by_split.items(), key=lambda item: -len(item[1])):
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD004",
                    sequence=sequence,
                    title=f"Near-duplicate redundancy inside '{split}'",
                    category=Category.DUPLICATE,
                    severity=Severity.LOW,
                    status=AuditStatus.WARNING,
                    evidence_type=EvidenceType.HEURISTIC,
                    confidence=Confidence.MEDIUM,
                    formal_impact=FormalImpact.NONE,
                    affected=[r.sample_id for a, b, _ in group for r in (a, b)],
                    source_split=split,
                    description=f"{len(group)} near-identical pair(s) sit inside {split}.",
                    why_it_matters=(
                        "Redundancy within one split is not leakage. It inflates apparent class support and "
                        "can make a small class look better represented than it is."
                    ),
                    evidence={
                        "method": "phash",
                        "hamming_threshold": threshold,
                        "pairs": [
                            {"image_a": a.sample_id, "image_b": b.sample_id, "hamming_distance": d}
                            for a, b, d in sorted(group, key=lambda item: item[2])[:20]
                        ],
                    },
                    limitations=limitations,
                    metadata={"scope": "within_split"},
                )
            )
            sequence += 1

    if buckets_truncated:
        findings.append(
            build_finding(
                ctx,
                rule_id="DD004",
                sequence=sequence,
                title="Near-duplicate search truncated by bucket size",
                category=Category.DUPLICATE,
                severity=Severity.LOW,
                status=AuditStatus.INCONCLUSIVE,
                evidence_type=EvidenceType.HEURISTIC,
                confidence=Confidence.LOW,
                formal_impact=FormalImpact.NONE,
                description=(
                    f"{buckets_truncated} hash bucket(s) exceeded max_bucket_size={max_bucket} and were not "
                    "compared exhaustively. Repetitive or near-uniform imagery is the usual cause."
                ),
                why_it_matters=(
                    "Some near-duplicate pairs may have been missed. Reporting PASS here would be false "
                    "confidence, so coverage is marked incomplete."
                ),
                evidence={"max_bucket_size": max_bucket, "truncated_buckets": buckets_truncated},
                limitations=limitations,
            )
        )
    return findings


def _band_candidates(
    records: list[SampleRecord], threshold: int, max_bucket: int
) -> tuple[list[tuple[SampleRecord, SampleRecord, int]], int]:
    """Exact-match banding over bit bands: superset of all pairs within Hamming distance."""
    bands = threshold + 1
    bits = len(records[0].phash or "") * 4  # hex chars -> bits
    band_width = max(bits // bands, 1)
    index: dict[tuple[int, str], list[SampleRecord]] = defaultdict(list)
    for record in records:
        bitstring = format(int(record.phash or "0", 16), f"0{bits}b")
        for band in range(bands):
            key = (band, bitstring[band * band_width : (band + 1) * band_width])
            index[key].append(record)
    seen: set[tuple[str, str]] = set()
    distances: list[tuple[SampleRecord, SampleRecord, int]] = []
    truncated = 0
    lookup = {record.sample_id: record for record in records}
    for members in index.values():
        if len(members) < 2:
            continue
        if len(members) > max_bucket:
            truncated += 1
            members = members[:max_bucket]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                pair_key = _pair_key(a.sample_id, b.sample_id)
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                distance = hamming_hex(a.phash or "0", b.phash or "0")
                distances.append((lookup[a.sample_id], lookup[b.sample_id], distance))
    return distances, truncated


def _pair_key(left: str, right: str) -> tuple[str, str]:
    """Order-independent key, so (a, b) and (b, a) are the same pair."""
    return (left, right) if left <= right else (right, left)


def _group_by_pair(
    ctx: AuditContext, matches: list[tuple[SampleRecord, SampleRecord, int]]
) -> list[tuple[str, str, list[tuple[SampleRecord, SampleRecord, int]]]]:
    grouped: dict[tuple[str, str], list[tuple[SampleRecord, SampleRecord, int]]] = defaultdict(list)
    for a, b, d in matches:
        grouped[_pair_key(a.split, b.split)].append((a, b, d))
    ordered = sorted(
        grouped.items(),
        key=lambda item: (_pair_priority(ctx, item[0][0], item[0][1]), -len(item[1])),
    )
    return [(key[0], key[1], value) for key, value in ordered]


def near_duplicate_settings(config: Config) -> dict[str, Any]:
    item = config.policies.item("near_duplicate")
    settings = item.extra_settings()
    return {
        "enabled": item.enabled,
        "method": settings.get("method", "phash"),
        "hamming_threshold": int(settings.get("hamming_threshold", 6)),
        "max_bucket_size": int(settings.get("max_bucket_size", 200)),
    }
