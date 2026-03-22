# inference_engine.py
# Loads the saved XGBoost model and runs predictions per cycle.
# Input features: queue_length, hour, minute, day_of_week, junction_id
# Output: predicted phase_duration_remaining

import pickle
from datetime import datetime

MODEL_PATH = "../model/model.ubj"

def load_model(path: str = MODEL_PATH):
    """
    Load the XGBoost model from disk.
    """
    pass


def predict(model, junction_id: int, queue_length: int, timestamp: datetime) -> dict:
    """
    Run inference for a single junction.
    Returns: { phase_duration_predicted: float }
    """
    pass
