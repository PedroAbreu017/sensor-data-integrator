import pandas as pd
import numpy as np
import pytest
from api.models import DataQuality
from api.services.validator import DataValidator


@pytest.fixture
def validator():
    return DataValidator()


@pytest.fixture
def valid_df():
    return pd.DataFrame({
        "timestamp": ["2024-01-01T00:00:00", "2024-01-01T00:30:00", "2024-01-01T01:00:00"],
        "value": [72.5, 73.1, 72.8],
        "tag_id": [1, 1, 1],
        "asset_id": [1, 1, 1],
        "equipment_id": [1, 1, 1],
    })


# ─── Structure ────────────────────────────────────────────────────────────────

def test_valid_dataframe_passes(validator, valid_df):
    df, errors = validator.validate(valid_df, "test.csv")
    assert all(df["quality"] == DataQuality.SAUDAVEL.value)
    assert len(errors) == 0


def test_missing_column_returns_error(validator):
    df = pd.DataFrame({"timestamp": ["2024-01-01"], "value": [1.0]})
    _, errors = validator.validate(df, "test.csv")
    reasons = [e.reason for e in errors]
    assert any("tag_id" in r for r in reasons)


def test_invalid_timestamp_marked_outlier(validator):
    df = pd.DataFrame({
        "timestamp": ["not-a-date", "2024-01-01T00:30:00"],
        "value": [72.5, 73.1],
        "tag_id": [1, 1],
        "asset_id": [1, 1],
        "equipment_id": [1, 1],
    })
    df_out, errors = validator.validate(df, "test.csv")
    assert df_out.iloc[0]["quality"] == DataQuality.OUTLIER
    assert df_out.iloc[1]["quality"] == DataQuality.SAUDAVEL


def test_non_numeric_value_marked_outlier(validator):
    df = pd.DataFrame({
        "timestamp": ["2024-01-01T00:00:00", "2024-01-01T00:30:00"],
        "value": ["abc", 73.1],
        "tag_id": [1, 1],
        "asset_id": [1, 1],
        "equipment_id": [1, 1],
    })
    df_out, errors = validator.validate(df, "test.csv")
    assert df_out.iloc[0]["quality"] == DataQuality.OUTLIER


# ─── Duplicates ───────────────────────────────────────────────────────────────

def test_duplicate_rows_marked_outlier(validator):
    df = pd.DataFrame({
        "timestamp": ["2024-01-01T00:00:00", "2024-01-01T00:00:00", "2024-01-01T00:30:00"],
        "value": [72.5, 72.5, 73.1],
        "tag_id": [1, 1, 1],
        "asset_id": [1, 1, 1],
        "equipment_id": [1, 1, 1],
    })
    df_out, errors = validator.validate(df, "test.csv")
    assert df_out.iloc[1]["quality"] == DataQuality.OUTLIER
    assert df_out.iloc[0]["quality"] == DataQuality.SAUDAVEL
    assert any("duplicate" in e.reason.lower() for e in errors)


# ─── Spike ────────────────────────────────────────────────────────────────────

def test_spike_detected(validator):
    base = [72.5, 72.6, 72.4, 72.7, 72.5, 72.3, 72.6, 72.4, 72.7, 72.5,
            72.4, 72.6, 72.5, 72.7, 72.4, 72.6, 72.5, 72.3, 72.6, 72.4]
    values = base[:10] + [500.0] + base[10:]
    df = pd.DataFrame({
        "timestamp": [f"2024-01-01T{i:02d}:00:00" for i in range(21)],
        "value": values,
        "tag_id": [1] * 21,
        "asset_id": [1] * 21,
        "equipment_id": [1] * 21,
    })
    df_out, errors = validator.validate(df, "test.csv")
    assert df_out.iloc[10]["quality"] in [DataQuality.SPIKE, DataQuality.OUTLIER_SPIKE]
    assert any("spike" in e.reason.lower() for e in errors)


def test_no_spike_on_stable_data(validator):
    base = [72.5, 72.6, 72.4, 72.7, 72.5, 72.3, 72.6, 72.4, 72.7, 72.5,
            72.4, 72.6, 72.5, 72.7, 72.4, 72.6, 72.5, 72.3, 72.6, 72.4]
    df = pd.DataFrame({
        "timestamp": [f"2024-01-01T{i:02d}:00:00" for i in range(20)],
        "value": base,
        "tag_id": [1] * 20,
        "asset_id": [1] * 20,
        "equipment_id": [1] * 20,
    })
    df_out, errors = validator.validate(df, "test.csv")
    spike_errors = [e for e in errors if "spike" in e.reason.lower()]
    assert len(spike_errors) == 0

# ─── Frozen sensor ────────────────────────────────────────────────────────────

def test_frozen_sensor_detected(validator):
    values = [72.5] * 20
    df = pd.DataFrame({
        "timestamp": [f"2024-01-01T{i:02d}:00:00" for i in range(20)],
        "value": values,
        "tag_id": [1] * 20,
        "asset_id": [1] * 20,
        "equipment_id": [1] * 20,
    })
    df_out, errors = validator.validate(df, "test.csv")
    assert any("frozen" in e.reason.lower() for e in errors)


def test_frozen_not_triggered_below_threshold(validator):
    values = [72.5, 72.5, 72.5, 72.6, 72.7]
    df = pd.DataFrame({
        "timestamp": [f"2024-01-01T{i:02d}:00:00" for i in range(5)],
        "value": values,
        "tag_id": [1] * 5,
        "asset_id": [1] * 5,
        "equipment_id": [1] * 5,
    })
    df_out, errors = validator.validate(df, "test.csv")
    frozen_errors = [e for e in errors if "frozen" in e.reason.lower()]
    assert len(frozen_errors) == 0


# ─── Empty dataframe ──────────────────────────────────────────────────────────

def test_empty_dataframe_returns_no_errors(validator):
    df = pd.DataFrame()
    df_out, errors = validator.validate(df, "test.csv")
    assert df_out.empty
    assert len(errors) == 0