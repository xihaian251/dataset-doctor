# unsafe_duplicate

Planted: 5 train rows copied into `test.csv` verbatim, `record_id` included, so the two files share byte-identical records. No post-outcome column and no other entity is shared. Note that DD005 fires here too: a verbatim copy always carries its `patient_id` across the boundary with it, so an exact duplicate is unavoidably also an entity overlap. The two findings describe one fault seen from two sides, and DD003's evidence is the sharper of the pair.

Regenerate: `python examples/build.py`
