import asyncio
import logging
import shutil
from pathlib import Path

from api.models import JobStatus
from api.routers.upload import update_job
from core.message_broker import consume, publish, QUEUES

logger = logging.getLogger("integrator.worker")


async def process_upload(message: dict):
    job_id = message["job_id"]
    tenant = message["tenant"]
    file_path = Path(message["file_path"])

    logger.info(f"[worker] Processing job {job_id} — tenant={tenant}")
    update_job(job_id, JobStatus.RUNNING)

    try:
        if tenant == "ORION":
            from api.services.orion_service import OrionService
            service = OrionService()
        elif tenant == "NEXUS":
            from api.services.nexus_service import NexusService
            service = NexusService()
        else:
            from api.services.atlas_service import AtlasService
            service = AtlasService()

        result = service.process_file(file_path)
        status = JobStatus.DONE if not result.errors else JobStatus.FAILED
        update_job(job_id, status, result)
        logger.info(f"[worker] ✅ Job {job_id} finished — status={status.value}")

        # Publish quality event
        healthy = result.records_processed - len(result.errors)
        spikes = sum(1 for e in result.errors if "spike" in e.reason.lower())
        frozen = sum(1 for e in result.errors if "frozen" in e.reason.lower())
        duplicates = sum(1 for e in result.errors if "duplicate" in e.reason.lower())
        outliers = len(result.errors) - spikes - frozen - duplicates

        await publish(QUEUES["quality.events"], {
            "job_id": job_id,
            "tenant": tenant,
            "filename": file_path.name,
            "records_processed": result.records_processed,
            "records_healthy": healthy,
            "records_outlier": outliers,
            "records_spike": spikes,
            "records_frozen": frozen,
            "records_duplicate": duplicates,
        })
        logger.info(f"[worker] 📊 Quality event published for job {job_id}")

    except Exception as e:
        logger.error(f"[worker] ✗ Job {job_id} failed: {e}", exc_info=True)
        update_job(job_id, JobStatus.FAILED)
    finally:
        shutil.rmtree(file_path.parent, ignore_errors=True)


async def start_workers():
    logger.info("[worker] Starting consumers...")
    await asyncio.gather(
        consume(QUEUES["upload.orion"], process_upload),
        consume(QUEUES["upload.nexus"], process_upload),
        consume(QUEUES["upload.atlas"], process_upload),
    )


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
    )
    asyncio.run(start_workers())