from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class AppEnv(str, Enum):
    DEV = "dev"
    TEST = "test"
    HOMOLOG = "hom"
    PROD = "prod"


class TenantEnum(str, Enum):
    ORION = "ORION"
    NEXUS = "NEXUS"
    ATLAS = "ATLAS"


class ValidationStage(str, Enum):
    PARSE = "parse"
    VALIDATE = "validate"
    UPLOAD = "upload"


class DataQuality(str, Enum):
    SAUDAVEL = "saudavel"
    OUTLIER = "outlier"
    SPIKE = "spike"
    CONGELADO = "congelado"
    OUTLIER_SPIKE = "outlier_spike"
    CONGELADO_SPIKE = "congelado_spike"
    OUTLIER_CONGELADO = "outlier_congelado"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class ErrorDetail(BaseModel):
    file: str
    stage: ValidationStage
    reason: str
    quality: Optional[str] = None
    row_index: Optional[int] = None


class ProcessingResult(BaseModel):
    tenant: str
    environment: str
    files_received: int = 0
    records_processed: int = 0
    parts_uploaded: int = 0
    validation: Optional[str] = None
    errors: List[ErrorDetail] = []
    duration_seconds: Optional[float] = None


class UploadResponse(BaseModel):
    job_id: str
    tenant: TenantEnum
    environment: str
    status: JobStatus
    message: str
    submitted_at: datetime
    result: Optional[ProcessingResult] = None