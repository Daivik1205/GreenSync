# train.py
# Trains an XGBoost regression model on the synthetic dataset.
# Prints MAE and RMSE. Saves model as model.ubj.

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb
import numpy as np

DATASET_PATH = "dataset.csv"
MODEL_OUTPUT = "model.ubj"

FEATURES = ["queue_length", "hour", "minute", "day_of_week", "junction_id"]
TARGET = "phase_duration_remaining"


def train(dataset_path: str = DATASET_PATH):
    """
    Load dataset, train XGBoost regressor, evaluate, and save model.
    """
    pass


if __name__ == "__main__":
    train()
