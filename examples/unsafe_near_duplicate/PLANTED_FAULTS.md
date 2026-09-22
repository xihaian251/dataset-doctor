# unsafe_near_duplicate

Planted: 3 pairs that straddle the split boundary after a brightness change (1.06x + 4). The pixels differ, so no sha256 matches; only a perceptual hash sees them. This is the fault an exact-duplicate check is blind to.

Regenerate: `python examples/build.py`
