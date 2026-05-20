import logging
import requests

logger = logging.getLogger("integrator.warehouse_client")


class DataWarehouseClient:
    """
    HTTP client for sending processed sensor data to the Data Warehouse API.
    """

    def __init__(self, base_url: str, tenant: str):
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant

    def upload_csv(self, csv_path: str) -> int:
        url = f"{self.base_url}/v1/warehouse/integrator/ingest"
        params = {"X-Tenant": self.tenant}

        logger.info(f"[{self.tenant}] 📤 Uploading CSV: {csv_path}")

        with open(csv_path, "rb") as f:
            response = requests.post(
                url,
                params=params,
                files={"file": (csv_path, f, "text/csv")},
                timeout=120,
            )

        raw = response.text.strip()
        logger.info(f"[{self.tenant}] 🔎 Response: {response.status_code} {raw}")

        response.raise_for_status()

        try:
            return int(raw)
        except ValueError:
            return 0