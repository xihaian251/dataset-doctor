# unsafe_image_label_conflict

Planted: one image saved under three different class folders - two in train, one in test. Identical content, three labels, so the label space rather than the split boundary is what is broken. DD003 reports the same files as an exact cross-split duplicate: with one copy inside test, both readings are true.

Regenerate: `python examples/build.py`
