import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.upload import upload_router, jobs_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.worker import start_workers
    task = asyncio.create_task(start_workers())
    yield
    task.cancel()


app = FastAPI(
    title="Sensor Data Integrator",
    description="Multi-tenant service for ingesting, validating and routing industrial sensor data.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(jobs_router)


@app.get("/health", tags=["monitoring"])
def health():
    return {"status": "ok", "service": "sensor-data-integrator"}