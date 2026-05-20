import uuid
import logging
import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from api.config import get_settings
from api.models import TenantEnum, UploadResponse, JobStatus
from core.message_broker import publish, QUEUES

logger = logging.getLogger("integrator.router")

_jobs: Dict[str, UploadResponse] = {}

_allowed_ext = {
    TenantEnum.ORION: {".csv", ".txt", ".xlsx"},
    TenantEnum.NEXUS: {".csv"},
    TenantEnum.ATLAS: {".csv", ".xlsx"},
}

upload_router = APIRouter(prefix="/upload", tags=["integration"])
jobs_router = APIRouter(prefix="/jobs", tags=["monitoring"])


@upload_router.post("", response_model=UploadResponse, status_code=202)
async def upload_file(
    tenant: TenantEnum = Form(...),
    file: UploadFile = File(...),
):
    settings = get_settings()

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _allowed_ext[tenant]:
        raise HTTPException(
            status_code=422,
            detail=f"Tenant {tenant} accepts: {_allowed_ext[tenant]}. Received: '{suffix}'",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File {size_mb:.1f}MB exceeds limit of {settings.max_upload_size_mb}MB",
        )

    job_id = str(uuid.uuid4())
    job_dir = Path(settings.temp_dir) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / Path(file.filename).name

    with open(file_path, "wb") as f:
        f.write(contents)

    logger.info(f"[{job_id}] Received: {file.filename} ({size_mb:.2f}MB) tenant={tenant}")

    response = UploadResponse(
        job_id=job_id,
        tenant=tenant,
        environment=settings.app_env.value,
        status=JobStatus.PENDING,
        message=f"'{file.filename}' received. Queued for processing.",
        submitted_at=datetime.now(timezone.utc),
    )
    _jobs[job_id] = response

    # Publish to RabbitMQ
    queue_name = QUEUES[f"upload.{tenant.value.lower()}"]
    await publish(queue_name, {
        "job_id": job_id,
        "tenant": tenant.value,
        "file_path": str(file_path),
        "filename": file.filename,
    })

    return response


@jobs_router.get("/{job_id}", response_model=UploadResponse)
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@jobs_router.get("", response_model=list[UploadResponse])
def list_jobs(tenant: TenantEnum = None, status: JobStatus = None):
    jobs = list(_jobs.values())
    if tenant:
        jobs = [j for j in jobs if j.tenant == tenant]
    if status:
        jobs = [j for j in jobs if j.status == status]
    return sorted(jobs, key=lambda j: j.submitted_at, reverse=True)


def update_job(job_id: str, status: JobStatus, result=None):
    if job_id in _jobs:
        _jobs[job_id].status = status
        if result:
            _jobs[job_id].result = result