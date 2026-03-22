# generate_dataset.py
# Generates a synthetic training dataset for the XGBoost signal phase predictor.
# Features: queue_length, hour, minute, day_of_week, junction_id (encoded)
# Target:   phase_duration_remaining (seconds)
# Calibrated to Bengaluru peak/off-peak traffic patterns.

import pandas as pd
import numpy as np


def generate(n_samples: int = 50000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic dataset and return as DataFrame.
    """
    pass


if __name__ == "__main__":
    df = generate()
    df.to_csv("dataset.csv", index=False)
    print(f"Dataset saved: {len(df)} rows")
