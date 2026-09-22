# unsafe_image_duplicate

Planted: 4 train images copied byte-for-byte into `test/`. Same pixels, same sha256, different file name - the class of leakage a checksum-based dedup does catch, isolated from everything else.

Regenerate: `python examples/build.py`
