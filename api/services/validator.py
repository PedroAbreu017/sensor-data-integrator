import logging
import pandas as pd
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Tuple, List

from api.models import DataQuality, ErrorDetail, ValidationStage

logger = logging.getLogger("integrator.validator")


class DataValidator:
    """
    Validates and classifies sensor data before sending to the Data Warehouse API.

    Rules applied in order:
    1. Structural validation  — invalid timestamp, missing columns
    2. Duplicates             — composite key tag_id + timestamp
    3. Timestamp range        — too old or in the future
    4. Spike                  — abrupt jump via MAD
    5. Frozen                 — same value for N consecutive readings
    6. Against database       — historical duplicate check
    """

    def __init__(self):
        self._max_age_years = 10
        self._max_future_days = 1
        self._frozen_threshold = 5

    def validate(
        self,
        df: pd.DataFrame,
        filename: str,
        db_config: dict = None,
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []

        if df.empty:
            return df, errors

        df = df.copy()
        df["quality"] = DataQuality.SAUDAVEL

        df, errs = self._check_structure(df, filename)
        errors.extend(errs)

        df, errs = self._check_duplicates(df, filename)
        errors.extend(errs)

        df, errs = self._check_timestamp_range(df, filename)
        errors.extend(errs)

        df, errs = self._check_spike(df, filename)
        errors.extend(errs)

        df, errs = self._check_frozen(df, filename)
        errors.extend(errs)

        if db_config:
            df, errs = self._check_against_database(df, filename, db_config)
            errors.extend(errs)

        return df, errors

    def _check_structure(
        self, df: pd.DataFrame, filename: str
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []

        for col in ["timestamp", "tag_id", "value"]:
            if col not in df.columns:
                errors.append(
                    ErrorDetail(
                        file=filename,
                        stage=ValidationStage.VALIDATE,
                        reason=f"Required column missing: '{col}'",
                    )
                )

        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        invalid = ts.isna()
        if invalid.any():
            df.loc[invalid, "quality"] = DataQuality.OUTLIER
            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{invalid.sum()} rows with invalid timestamp",
                )
            )

        values = pd.to_numeric(df["value"], errors="coerce")
        nulls = values.isna()
        if nulls.any():
            df.loc[nulls, "quality"] = DataQuality.OUTLIER
            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{nulls.sum()} rows with non-numeric value",
                )
            )

        return df, errors

    def _check_duplicates(
        self, df: pd.DataFrame, filename: str
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []
        if "tag_id" not in df.columns or "timestamp" not in df.columns:
            return df, errors
    
        duplicated = df.duplicated(subset=["tag_id", "timestamp"], keep="first")
        count = duplicated.sum()

        if count > 0:
            df.loc[duplicated, "quality"] = DataQuality.OUTLIER
            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{count} duplicate rows by tag_id + timestamp",
                )
            )

        return df, errors

    def _check_timestamp_range(
        self, df: pd.DataFrame, filename: str
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []

        now = datetime.now(timezone.utc)
        min_date = now - timedelta(days=365 * self._max_age_years)
        max_date = now + timedelta(days=self._max_future_days)

        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

        too_old = ts < min_date
        if too_old.any():
            df.loc[too_old, "quality"] = DataQuality.OUTLIER
            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{too_old.sum()} rows with timestamp before {min_date.year}",
                )
            )

        in_future = ts > max_date
        if in_future.any():
            df.loc[in_future, "quality"] = DataQuality.OUTLIER
            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{in_future.sum()} rows with timestamp in the future",
                )
            )

        return df, errors

    def _check_spike(
        self, df: pd.DataFrame, filename: str, deviations: float = 3.0
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []

        if "tag_id" not in df.columns or "value" not in df.columns:
            return df, errors

        values = pd.to_numeric(df["value"], errors="coerce")
        spike_mask = pd.Series(False, index=df.index)

        for tag_id in df["tag_id"].unique():
            tag_mask = df["tag_id"] == tag_id
            vals = values[tag_mask]

            if len(vals) < 4:
                continue

            median = vals.median()
            mad = (vals - median).abs().median()

            if mad == 0:
                continue

            upper = median + (deviations * mad)
            lower = median - (deviations * mad)

            spike_tag = tag_mask & ((values > upper) | (values < lower))
            spike_mask = spike_mask | spike_tag

        count = spike_mask.sum()
        if count > 0:
            already_outlier = df["quality"] == DataQuality.OUTLIER
            df.loc[spike_mask & ~already_outlier, "quality"] = DataQuality.SPIKE
            df.loc[spike_mask & already_outlier, "quality"] = DataQuality.OUTLIER_SPIKE
            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{count} rows with spike detected ({deviations} MAD deviations)",
                )
            )

        return df, errors

    def _check_frozen(
        self, df: pd.DataFrame, filename: str
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []

        if "tag_id" not in df.columns or "value" not in df.columns:
            return df, errors

        values = pd.to_numeric(df["value"], errors="coerce")
        frozen_mask = pd.Series(False, index=df.index)

        for tag_id in df["tag_id"].unique():
            tag_mask = df["tag_id"] == tag_id
            vals = values[tag_mask]

            if len(vals) < self._frozen_threshold:
                continue

            repeated = vals == vals.shift(1)
            counter = repeated.groupby((~repeated).cumsum()).cumsum()
            frozen_tag = tag_mask & (counter >= self._frozen_threshold - 1)
            frozen_mask = frozen_mask | frozen_tag

        count = frozen_mask.sum()
        if count > 0:
            already_spike = df["quality"] == DataQuality.SPIKE
            already_outlier = df["quality"] == DataQuality.OUTLIER

            df.loc[frozen_mask & ~already_spike & ~already_outlier, "quality"] = DataQuality.CONGELADO
            df.loc[frozen_mask & already_spike, "quality"] = DataQuality.CONGELADO_SPIKE
            df.loc[frozen_mask & already_outlier, "quality"] = DataQuality.OUTLIER_CONGELADO

            errors.append(
                ErrorDetail(
                    file=filename,
                    stage=ValidationStage.VALIDATE,
                    reason=f"{count} rows with frozen sensor (threshold={self._frozen_threshold})",
                )
            )

        return df, errors

    def _check_against_database(
        self, df: pd.DataFrame, filename: str, db_config: dict
    ) -> Tuple[pd.DataFrame, List[ErrorDetail]]:
        errors = []

        if "tag_id" not in df.columns or "timestamp" not in df.columns:
            return df, errors

        try:
            ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
            ts_min = ts.min()
            ts_max = ts.max()
            tag_ids = df["tag_id"].dropna().unique().tolist()

            if not tag_ids or pd.isna(ts_min):
                return df, errors

            conn = psycopg2.connect(**db_config)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT tag_id, timestamp
                FROM sensor_readings
                WHERE tag_id = ANY(%s)
                AND timestamp BETWEEN %s AND %s;
                """,
                (tag_ids, ts_min, ts_max),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            if not rows:
                return df, errors

            db_keys = set(
                (
                    int(row[0]),
                    pd.Timestamp(row[1]).tz_localize("UTC")
                    if pd.Timestamp(row[1]).tzinfo is None
                    else pd.Timestamp(row[1]).tz_convert("UTC"),
                )
                for row in rows
            )

            def already_exists(row):
                try:
                    ts_row = (
                        pd.Timestamp(row["timestamp"]).tz_localize("UTC")
                        if pd.Timestamp(row["timestamp"]).tzinfo is None
                        else pd.Timestamp(row["timestamp"]).tz_convert("UTC")
                    )
                    return (int(row["tag_id"]), ts_row) in db_keys
                except Exception:
                    return False

            exists_mask = df.apply(already_exists, axis=1)
            count = exists_mask.sum()

            if count > 0:
                df.loc[exists_mask, "quality"] = DataQuality.OUTLIER
                errors.append(
                    ErrorDetail(
                        file=filename,
                        stage=ValidationStage.VALIDATE,
                        reason=f"{count} rows already exist in database (historical duplicate)",
                    )
                )
                logger.info(f"[validator] {count} records blocked — already exist in database")

        except Exception as e:
            logger.warning(f"[validator] _check_against_database skipped: {e}")

        return df, errors