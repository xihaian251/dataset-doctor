# corrupt_image

Planted: a truncated JPEG and a zero-byte PNG. Neither is leakage; both silently shrink a pipeline that skips unloadable files, so the coverage number is the finding.

Regenerate: `python examples/build.py`
