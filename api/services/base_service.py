import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from api.models import ErrorDetail, ProcessingResult, ValidationStage


class BaseIntegradorService(ABC):

    @abstractmethod
    def process_file(self, path):
        pass

    def _start(self) -> float:
        return time.time()

    def _error(
        self, file: str, reason: str, stage: ValidationStage
    ) -> ErrorDetail:
        return ErrorDetail(file=file, stage=stage, reason=reason)

    def _make_result(
        self,
        start: float,
        records_processed: int = 0,
        parts_uploaded: int = 0,
        errors=None,
    ) -> ProcessingResult:
        from api.config import get_settings
        settings = get_settings()

        return ProcessingResult(
            tenant=str(self.tenant.value),
            environment=settings.app_env.value,
            files_received=1,
            records_processed=records_processed,
            parts_uploaded=parts_uploaded,
            errors=errors or [],
            duration_seconds=round(time.time() - start, 2),
        )