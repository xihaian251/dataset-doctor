"""Rule detectors. Each module owns one family of facts and never a verdict.

Importing a detector module must not pull in optional dependencies: image-specific
code imports ``imagehash`` lazily inside the function so a tabular audit works on a
machine without the ``image`` extra installed.
"""

from __future__ import annotations
