import logging
import pandas as pd
from pathlib import Path
from api.config import get_settings
from api.models import TenantEnum, ValidationStage
from api.services.base_service import BaseIntegradorService
from api.services.validator import DataValidator

logger = logging.getLogger("integrator.orion")


class OrionService(BaseIntegradorService):
    tenant = TenantEnum.ORION

    def __init__(self):
        self._settings = get_settings()
        self._validator = DataValidator()

    def process_file(self, path: Path):
        start = self._start()
        errors = []
        parts_uploaded = 0
        records_processed = 0

        try:
            from core.orion_ingester import OrionDataIngester

            ingester = OrionDataIngester(
                tenant="ORION",
                base_dir_arg=str(path.parent),
                warehouse_url=self._settings.warehouse_url,
            )

            suffix = path.suffix.lower()

            if suffix == ".csv":
                for converted_path in ingester.convert_csv(path):
                    df = pd.read_csv(converted_path)
                    records_processed += len(df)

                    df_clean, val_errors = self._validator.validate(
                        df,
                        path.name,
                        db_config=ingester.DB_CONFIG,
                    )
                    errors.extend(val_errors)

                    df_upload = df_clean[df_clean["quality"] == "saudavel"].drop(
                        columns=["quality"]
                    )
                    if df_upload.empty:
                        logger.warning(f"[ORION] No healthy rows in {converted_path.name}")
                        continue

                    ok = ingester._process_converted_with_api_parallel(converted_path)
                    if ok:
                        parts_uploaded += 1
                    else:
                        errors.append(self._error(path.name, "Upload failed to Data Warehouse API", ValidationStage.UPLOAD))

            elif suffix == ".xlsx":
                try:
                    import openpyxl  # noqa
                except ImportError:
                    errors.append(self._error(path.name, "openpyxl not installed", ValidationStage.PARSE))
                    return self._make_result(start=start, errors=errors)

                for converted_path in ingester.convert_xlsx(path):
                    df = pd.read_csv(converted_path)
                    records_processed += len(df)

                    df_clean, val_errors = self._validator.validate(
                        df,
                        path.name,
                        db_config=ingester.DB_CONFIG,
                    )
                    errors.extend(val_errors)

                    df_upload = df_clean[df_clean["quality"] == "saudavel"].drop(
                        columns=["quality"]
                    )
                    if df_upload.empty:
                        logger.warning(f"[ORION] No healthy rows in {converted_path.name}")
                        continue

                    ok = ingester._process_converted_with_api_parallel(converted_path)
                    if ok:
                        parts_uploaded += 1
                    else:
                        errors.append(self._error(path.name, "Upload failed to Data Warehouse API", ValidationStage.UPLOAD))

            else:
                # TXT flow
                df_raw = ingester._read_txt(path)
                if df_raw.empty:
                    errors.append(self._error(path.name, "Empty DataFrame after reading", ValidationStage.PARSE))
                    return self._make_result(start=start, errors=errors)

                df_parsed = ingester._parse_data(df_raw, path)
                if df_parsed.empty:
                    errors.append(self._error(path.name, "No valid records after parsing", ValidationStage.PARSE))
                    return self._make_result(start=start, errors=errors)

                records_processed = len(df_parsed)

                df_clean, val_errors = self._validator.validate(
                    df_parsed,
                    path.name,
                    db_config=ingester.DB_CONFIG,
                )
                errors.extend(val_errors)

                df_upload = df_clean[df_clean["quality"] == "saudavel"].drop(columns=["quality"])
                if df_upload.empty:
                    logger.warning("[ORION] No healthy rows after validation")
                    return self._make_result(start=start, records_processed=records_processed, errors=errors)

                csv_out = path.with_name(f"{path.stem}_converted.csv")
                df_upload.to_csv(csv_out, index=False)
                ok = ingester._process_converted_with_api_parallel(csv_out)
                if ok:
                    parts_uploaded += 1
                else:
                    errors.append(self._error(path.name, "Upload failed to Data Warehouse API", ValidationStage.UPLOAD))

        except ImportError as e:
            logger.error(f"[ORION] core/orion_ingester.py not found: {e}")
            errors.append(self._error(path.name, str(e), ValidationStage.PARSE))
        except Exception as e:
            logger.error(f"[ORION] Unexpected error: {e}", exc_info=True)
            errors.append(self._error(path.name, str(e), ValidationStage.UPLOAD))

        return self._make_result(
            start=start,
            records_processed=records_processed,
            parts_uploaded=parts_uploaded,
            errors=errors,
        )