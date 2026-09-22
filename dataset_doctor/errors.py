"""Exception hierarchy. Config errors exit 2, internal errors exit 3 (spec section 80)."""

from __future__ import annotations


class DatasetDoctorError(Exception):
    """Base class for all expected failures."""


class ConfigError(DatasetDoctorError):
    """Bad or unparseable configuration, unknown rule id, mutually exclusive options."""


class DiscoveryError(DatasetDoctorError):
    """The dataset structure could not be resolved."""


class EmptyDatasetError(DiscoveryError):
    """Zero samples discovered."""


class AdapterError(DatasetDoctorError):
    """A dataset could not be read by the selected adapter."""


class SnapshotError(DatasetDoctorError):
    """A snapshot is missing or unreadable."""


class DiffError(DatasetDoctorError):
    """Two datasets cannot be compared."""


class SplitError(DatasetDoctorError):
    """A requested re-split cannot be performed safely (bad column, occupied output)."""


class InternalError(DatasetDoctorError):
    """Unexpected failure; reported as exit code 3."""
