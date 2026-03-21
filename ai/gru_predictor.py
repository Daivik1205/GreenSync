# gru_predictor.py — Phase 6
# GRU (Gated Recurrent Unit) model for time-series traffic speed prediction.
# Input: sequence of past avg_speeds for a zone
# Output: predicted avg_speed N steps ahead

import numpy as np

SEQUENCE_LENGTH = 10   # how many past timesteps to use
FORECAST_HORIZON = 5   # how many steps ahead to predict


def build_model(input_dim: int = 1, hidden_units: int = 64):
    """
    Build and return a Keras GRU model.
    """
    # TODO: import tensorflow/keras and define GRU model
    pass


def train(model, X_train: np.ndarray, y_train: np.ndarray, epochs: int = 50):
    """
    Train GRU model on historical speed sequences.
    """
    pass


def predict(model, speed_history: list[float]) -> float:
    """
    Predict next speed given recent speed history.
    speed_history: list of last SEQUENCE_LENGTH avg_speed values
    Returns: predicted avg_speed (m/s)
    """
    pass


def save_model(model, path: str = "model/gru_model.keras"):
    pass


def load_model(path: str = "model/gru_model.keras"):
    pass
