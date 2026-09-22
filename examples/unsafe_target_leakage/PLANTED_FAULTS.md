# unsafe_target_leakage

Planted: `discharge_code` is written as `DC-{target+1:02d}` after the outcome is known, and `visit_lactate` is drawn from the label. No duplicated rows and no shared patients - the data is perfectly split and perfectly useless, which is the point. The first column is a deterministic relabeling (a verdict); the second only predicts well (a candidate a real biomarker would also produce).

Regenerate: `python examples/build.py`
