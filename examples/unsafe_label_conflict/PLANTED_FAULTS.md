# unsafe_label_conflict

Planted: 4 train records replicated in test with identical feature values, a new `record_id` and the label flipped. The features cannot separate these rows, so the label is the only thing that differs - a rate-noise or annotation-pipeline problem that lands inside the evaluation split. DD005 comes along for the same reason it does in `unsafe_duplicate`: the replicas keep their `patient_id`, so the entity crosses the boundary too.

Regenerate: `python examples/build.py`
