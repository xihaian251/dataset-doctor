# leaky_patient_dataset

Planted together: 6 train patients re-booked into test, 4 verbatim row copies, `discharge_code` as a deterministic relabeling of the label, `visit_lactate` drawn from the label, a test split enriched with the positive class, and a collection window where train (2026) is *later* than test (2024) - a backtest that predicts the past. The control for this fixture is `safe_tabular`.

Regenerate: `python examples/build.py`
