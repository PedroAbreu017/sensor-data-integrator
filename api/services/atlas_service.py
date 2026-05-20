import logging
import pandas as pd
from pathlib import Path
from api.config import get_settings
from api.models import TenantEnum, ValidationStage
from api.services.base_service import BaseIntegradorService
from api.services.validator import DataValidator

logger = logging.getLogger("integrator.atlas")


class AtlasService(BaseIntegradorService):
    tenant = TenantEnum.ATLAS

    def __init__(self):
        self._settings = get_settings()
        self._validator = DataValidator()

    def process_file(self, path: Path):
        start = self._start()
        errors = []
        parts_uploaded = 0
        records_processed = 0

        try:
            from core.atlas_ingester import AtlasDataIngester

            ingester = AtlasDataIngester(
                tenant="ATLAS",
                base_dir_arg=str(path.parent),
                warehouse_url=self._settings.warehouse_url,
            )

            suffix = path.suffix.lower()

            for converted_path in ingester.convert_csv(path) if suffix == ".csv" else ingester.convert_xlsx(path):
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
                    logger.warning(f"[ATLAS] No healthy rows in {converted_path.name}")
                    continue

                ok = ingester._process_converted_with_api_parallel(converted_path)
                if ok:
                    parts_uploaded += 1
                else:
                    errors.append(self._error(path.name, "Upload failed to Data Warehouse API", ValidationStage.UPLOAD))

        except ImportError as e:
            logger.error(f"[ATLAS] core/atlas_ingester.py not found: {e}")
            errors.append(self._error(path.name, str(e), ValidationStage.PARSE))
        except Exception as e:
            logger.error(f"[ATLAS] Unexpected error: {e}", exc_info=True)
            errors.append(self._error(path.name, str(e), ValidationStage.UPLOAD))

        return self._make_result(
            start=start,
            records_processed=records_processed,
            parts_uploaded=parts_uploaded,
            errors=errors,
        )