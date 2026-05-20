import logging
import io
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from fastapi import APIRouter, UploadFile, File, Query, HTTPException

from warehouse.app.config import DB_CONFIG

logger = logging.getLogger("warehouse.routes")

router = APIRouter()


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


@router.post("/v1/warehouse/integrator/ingest")
async def ingest(
    file: UploadFile = File(...),
    tenant: str = Query(..., alias="X-Tenant"),
):
    contents = await file.read()

    try:
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {e}")

    required = {"timestamp", "value", "tag_id", "asset_id", "equipment_id"}
    if not required.issubset(df.columns):
        raise HTTPException(
            status_code=422,
            detail=f"Missing columns: {required - set(df.columns)}"
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", "value", "tag_id"])
    df["quality"] = df.get("quality", "saudavel")

    records = [
        (
            row["timestamp"],
            float(row["value"]),
            int(row["asset_id"]),
            int(row["equipment_id"]),
            int(row["tag_id"]),
            str(row.get("quality", "saudavel")),
        )
        for _, row in df.iterrows()
    ]

    if not records:
        return 0

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO sensor_readings
                        (timestamp, value, asset_id, equipment_id, tag_id, quality)
                    VALUES %s
                    ON CONFLICT DO NOTHING;
                    """,
                    records,
                )
            conn.commit()
        logger.info(f"[{tenant}] ✅ {len(records)} records inserted")
        return len(records)
    except Exception as e:
        logger.error(f"[{tenant}] ✗ Error inserting records: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
def health():
    return {"status": "ok", "service": "data-warehouse-api"}