# leaky_image_dataset

Planted, at the spec's sizes: 10 exact duplicates (5 train images copied into test), 6 near-duplicate samples (3 pairs across the boundary), a 3-way label conflict (one image under three class folders), 1 truncated JPEG and 1 zero-byte PNG, plus a 28:8:14:8 class distribution. Nothing else is planted.

Regenerate: `python examples/build.py`
