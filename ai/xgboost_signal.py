# xgboost_signal.py — Phase 6
# XGBoost model for signal phase duration prediction.
# Features: queue_length, hour, minute, day_of_week, junction_id
# Target:   phase_duration_remaining (seconds)

import xgboost as xgb
import numpy as np
from datetime import datetime

MODEL_PATH = "model/xgb_signal.ubj"


def load(path: str = MODEL_PATH) -> xgb.XGBRegressor:
    model = xgb.XGBRegressor()
    model.load_model(path)
    return model


def predict(model: xgb.XGBRegressor, junction_id: int,
            queue_length: int, timestamp: datetime) -> float:
    features = np.array([[
        queue_length,
        timestamp.hour,
        timestamp.minute,
        timestamp.weekday(),
        junction_id,
    ]])
    return float(model.predict(features)[0])
