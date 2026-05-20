from enum import Enum
from functools import lru_cache
from pydantic_settings import BaseSettings


class AppEnv(str, Enum):
    DEV = "dev"
    TEST = "test"
    HOMOLOG = "hom"
    PROD = "prod"


TENANT_SEGMENTO = {
    "orion": "subsea",
    "nexus": "substation",
    "atlas": "subsea",
}


class Settings(BaseSettings):
    # Ambiente
    app_env: AppEnv = AppEnv.DEV
    app_version: str = "1.0.0"

    # Warehouse API
    warehouse_url_dev: str = "http://localhost:8096"
    warehouse_url_test: str = "http://localhost:8096"
    warehouse_url_hom: str = "http://TO_BE_DEFINED"
    warehouse_url_prod: str = "http://TO_BE_DEFINED"

    # Banco
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"

    # sensor
    db_name_sensor_subsea_dev: str = "dev_sensor_subsea_v0"
    db_name_sensor_subsea_test: str = "test_sensor_subsea_v0"
    db_name_sensor_substation_dev: str = "dev_sensor_substation_v0"
    db_name_sensor_substation_test: str = "test_sensor_substation_v0"

    # Upload
    temp_dir: str = "/tmp/integrator_uploads"
    max_upload_size_mb: int = 200

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @property
    def warehouse_url(self) -> str:
        return {
            AppEnv.DEV: self.warehouse_url_dev,
            AppEnv.TEST: self.warehouse_url_test,
            AppEnv.HOMOLOG: self.warehouse_url_hom,
            AppEnv.PROD: self.warehouse_url_prod,
        }[self.app_env]

    def db_config(self, tenant: str) -> dict:
        segmento = TENANT_SEGMENTO.get(tenant.lower())
        if segmento is None:
            raise ValueError(f"Tenant desconhecido: {tenant}")
        env = self.app_env.value
        key = f"db_name_sensor_{segmento}_{env}"
        db_name = getattr(self, key, None)
        if db_name is None:
            raise ValueError(
                f"Banco não configurado: tenant={tenant} segmento={segmento} env={env}"
            )
        return {
            "host": self.db_host,
            "port": self.db_port,
            "dbname": db_name,
            "user": self.db_user,
            "password": self.db_password,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()