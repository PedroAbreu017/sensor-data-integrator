import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from warehouse.app.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="Data Warehouse API",
    description="Receives processed sensor data from the Integrator and persists to the database.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)