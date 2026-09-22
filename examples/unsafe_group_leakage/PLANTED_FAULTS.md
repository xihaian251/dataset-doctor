# unsafe_group_leakage

Planted: patients p000-p003 re-booked into test under new `record_id`s (every other row, 10 rows total). No row is an exact duplicate, so a dedup script would miss this completely - only the entity column makes it visible.

Regenerate: `python examples/build.py`
