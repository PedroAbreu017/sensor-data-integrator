import logging
from pathlib import Path
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from concurrent.futures import ThreadPoolExecutor
from core.warehouse_client import DataWarehouseClient
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("integrator.nexus")

APP_ENV = os.getenv("APP_ENV", "dev")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv(f"DB_NAME_SENSOR_SUBSTATION_{APP_ENV.upper()}"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

WAREHOUSE_URL = {
    "dev": os.getenv("WAREHOUSE_URL_DEV", "http://localhost:8096"),
    "test": os.getenv("WAREHOUSE_URL_TEST", "http://localhost:8096"),
    "hom": os.getenv("WAREHOUSE_URL_HOM", "http://TO_BE_DEFINED"),
    "prod": os.getenv("WAREHOUSE_URL_PROD", "http://TO_BE_DEFINED"),
}[APP_ENV]

CHUNK_SIZE = 50_000
MAX_WORKERS = 1
MAX_RETRIES = 2

TAG_signal_label = {
    "VOLT_A": "voltage_a",
    "VOLT_B": "voltage_b",
    "VOLT_C": "voltage_c",
    "CURR_A": "current_a",
    "CURR_B": "current_b",
    "CURR_C": "current_c",
    "PWR_ACT": "active_power",
    "PWR_REACT": "reactive_power",
    "FREQ": "frequency",
}

EQUIPMENT_PREFIX = {
    "NX1.TRAFO_A": ("Nexus Substation 1 - Transformer A", "Nexus Substation 1"),
    "NX1.TRAFO_B": ("Nexus Substation 1 - Transformer B", "Nexus Substation 1"),
    "NX1.TRAFO_C": ("Nexus Substation 1 - Transformer C", "Nexus Substation 1"),
    "NX2.TRAFO_A": ("Nexus Substation 2 - Transformer A", "Nexus Substation 2"),
    "NX2.TRAFO_B": ("Nexus Substation 2 - Transformer B", "Nexus Substation 2"),
    "NX2.TRAFO_C": ("Nexus Substation 2 - Transformer C", "Nexus Substation 2"),
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def get_map_from_db(table, key_col="name", id_col="id"):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {id_col}, {key_col} FROM {table} ORDER BY {id_col};")
                rows = cur.fetchall()
        return {name: id for id, name in rows}
    except Exception as e:
        logger.error(f"✗ Error querying table {table}: {e}")
        return {}


def get_tag_to_equipment_map():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, equipment_id FROM tag;")
                rows = cur.fetchall()
        return {tag_id: eq_id for tag_id, eq_id in rows}
    except Exception as e:
        logger.error(f"✗ Error building tag->equipment map: {e}")
        return {}


def get_equipment_to_asset_map():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, asset_id FROM equipment;")
                rows = cur.fetchall()
        return {eq_id: asset_id for eq_id, asset_id in rows}
    except Exception as e:
        logger.error(f"✗ Error building equipment->asset map: {e}")
        return {}


def get_tag_to_signal_label_map():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, signal_label FROM tag;")
                rows = cur.fetchall()
        return {tag_id: signal_label for tag_id, signal_label in rows}
    except Exception as e:
        logger.error(f"✗ Error building tag->signal_label map: {e}")
        return {}


def ensure_asset(asset_name: str, industry_id: int = 1) -> int:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM asset WHERE name=%s;", (asset_name,))
                row = cur.fetchone()
                if row is not None:
                    logger.info(f"🔄 Asset already exists: {asset_name} (id={row[0]})")
                    return row[0]

                cur.execute("SELECT id FROM operation_status LIMIT 1;")
                op_row = cur.fetchone()
                op_id = op_row[0] if op_row else None
                if op_id is None:
                    cur.execute("INSERT INTO operation_status (name) VALUES (%s) RETURNING id;", ("ACTIVE",))
                    op_id = cur.fetchone()[0]

                cur.execute("SELECT id FROM industry WHERE id=%s;", (industry_id,))
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO industry (name, operation_status_id) VALUES (%s, %s) RETURNING id;",
                        ("Energy", op_id),
                    )
                    industry_id = cur.fetchone()[0]

                cur.execute(
                    "INSERT INTO asset (name, industry_id, state, operation_status_id) VALUES (%s, %s, %s, %s) RETURNING id;",
                    (asset_name, industry_id, "ACTIVE", op_id),
                )
                asset_id = cur.fetchone()[0]
                logger.info(f"✅ Asset created: {asset_name} (id={asset_id})")
            conn.commit()
        return asset_id
    except Exception as e:
        logger.error(f"✗ Error ensuring asset {asset_name}: {e}")
        raise


def ensure_equipment(equipment_name: str, asset_id: int, code: str = None) -> tuple[int, int]:
    if code is None:
        code = equipment_name
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, asset_id FROM equipment WHERE name=%s OR code=%s;",
                    (equipment_name, code),
                )
                row = cur.fetchone()
                if row is not None:
                    logger.info(f"🔄 Equipment already exists: {equipment_name} (id={row[0]})")
                    return row[0], row[1]

                cur.execute(
                    "INSERT INTO equipment (name, code, asset_id) VALUES (%s, %s, %s) RETURNING id;",
                    (equipment_name, code, asset_id),
                )
                equipment_id = cur.fetchone()[0]
                logger.info(f"✅ Equipment created: {equipment_name} (id={equipment_id})")
            conn.commit()
        return equipment_id, asset_id
    except Exception as e:
        logger.error(f"✗ Error ensuring equipment {equipment_name}: {e}")
        raise


def insert_missing_tags(missing_tags, equipment_id, signal_labels=None, descriptions=None):
    if not missing_tags:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                values = [
                    (tag, equipment_id, signal_labels.get(tag) if signal_labels else tag,
                     descriptions.get(tag) if descriptions else tag, "MEASURE", "")
                    for tag in missing_tags
                ]
                execute_values(
                    cur,
                    """
                    INSERT INTO tag (name, equipment_id, signal_label, description, type, unit)
                    VALUES %s
                    ON CONFLICT DO NOTHING;
                    """,
                    values,
                )
            conn.commit()
        logger.info(f"✅ Tags inserted: {list(missing_tags)}")
    except Exception as e:
        logger.error(f"✗ Error inserting tags: {e}")


def infer_signal_label(tag: str) -> str:
    tag_upper = tag.upper()
    suffix = tag_upper.split(".")[-1]
    mapping = {
        "VOLT_A": "voltage_a", "VOLT_B": "voltage_b", "VOLT_C": "voltage_c",
        "CURR_A": "current_a", "CURR_B": "current_b", "CURR_C": "current_c",
        "PWR_ACT": "active_power", "PWR_REACT": "reactive_power", "FREQ": "frequency",
    }
    return mapping.get(suffix)


class NexusDataIngester:
    DB_CONFIG = DB_CONFIG

    def __init__(self, tenant="NEXUS", base_dir_arg="data/nexus", warehouse_url=None):
        self.tenant = tenant
        self.data_dir = Path(base_dir_arg).resolve()
        self.warehouse_client = DataWarehouseClient(base_url=warehouse_url or WAREHOUSE_URL, tenant=self.tenant)

        self.tag_map = get_map_from_db("tag")
        self.asset_map = get_map_from_db("asset")
        self.equipment_map = get_map_from_db("equipment")
        self.tag_to_equipment = get_tag_to_equipment_map()
        self.equipment_to_asset = get_equipment_to_asset_map()
        self.tag_to_signal_label = get_tag_to_signal_label_map()

        logger.info(f"[{self.tenant}] Base: {self.data_dir}")
        logger.info(f"[{self.tenant}] ✅ assets={len(self.asset_map)} | equipments={len(self.equipment_map)} | tags={len(self.tag_map)}")

    def _reload_maps(self):
        self.tag_map = get_map_from_db("tag")
        self.tag_to_equipment = get_tag_to_equipment_map()
        self.equipment_to_asset = get_equipment_to_asset_map()
        self.tag_to_signal_label = get_tag_to_signal_label_map()

    def _resolve_context(self, tag: str):
        for prefix, ctx in EQUIPMENT_PREFIX.items():
            if tag.startswith(prefix):
                return ctx
        return None

    def convert_csv(self, csv_file: Path):
        with open(csv_file, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
        sep = ";" if ";" in first_line else ","
        df = pd.read_csv(csv_file, sep=sep, decimal=",", on_bad_lines="skip")

        if "tag_id" in df.columns and "value" in df.columns:
            logger.info(f"[{self.tenant}] Already converted CSV: {csv_file}")
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"])
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
            if "signal_label" not in df.columns:
                df["signal_label"] = df["tag_id"].map(self.tag_to_signal_label)
            df["month"] = df["timestamp"].str[:7]
            for month, df_month in df.groupby("month"):
                converted_path = csv_file.with_name(f"{csv_file.stem}_{month}_converted_ids.csv")
                df_month.drop(columns=["month"]).to_csv(converted_path, index=False)
                yield converted_path
            return

        for col in ["timestamp", "ts", "E3TimeStamp"]:
            if col in df.columns:
                df.rename(columns={col: "timestamp"}, inplace=True)
                break
        if "timestamp" not in df.columns:
            df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)

        if "value" not in df.columns and len(df.columns) > 2:
            df = df.melt(id_vars=["timestamp"], var_name="tag", value_name="value")

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        if "tag" in df.columns:
            df["tag_id"] = df["tag"].map(self.tag_map)
            df["equipment_id"] = df["tag_id"].map(self.tag_to_equipment)
            df["asset_id"] = df["equipment_id"].map(self.equipment_to_asset)
            df["signal_label"] = df["tag_id"].map(self.tag_to_signal_label)

        if "tag" in df.columns and df["tag_id"].isnull().any():
            missing_tags = df[df["tag_id"].isnull()]["tag"].unique()
            logger.warning(f"[{self.tenant}] ⚠ Tags without mapping: {len(missing_tags)}")

            signal_labels_map = {}
            descriptions_map = {}
            tags_per_equipment = {}

            for tag in missing_tags:
                ctx = self._resolve_context(tag)
                if ctx is None:
                    logger.error(f"[{self.tenant}] ✗ Tag without recognized prefix: {tag}")
                    continue

                equipment_name, asset_name = ctx
                asset_id = ensure_asset(asset_name)
                equipment_id, _ = ensure_equipment(equipment_name, asset_id)

                medida = infer_signal_label(tag)
                signal_labels_map[tag] = medida
                descriptions_map[tag] = tag

                if equipment_id not in tags_per_equipment:
                    tags_per_equipment[equipment_id] = []
                tags_per_equipment[equipment_id].append(tag)

            for eq_id, tags in tags_per_equipment.items():
                insert_missing_tags(tags, eq_id, signal_labels_map, descriptions_map)

            self._reload_maps()

            df["tag_id"] = df["tag"].map(self.tag_map)
            df["equipment_id"] = df["tag_id"].map(self.tag_to_equipment)
            df["asset_id"] = df["equipment_id"].map(self.equipment_to_asset)
            df["signal_label"] = df["tag_id"].map(self.tag_to_signal_label)
            df = df.dropna(subset=["tag_id"])

        if "value" in df.columns:
            df = df.dropna(subset=["value"])
            df = df[df["value"] != 0]
        else:
            logger.error(f"[{self.tenant}] ✗ CSV without 'value' column: {csv_file}")
            return

        cols = [c for c in ["timestamp", "value", "asset_id", "equipment_id", "tag_id", "signal_label"] if c in df.columns]
        df_out = df[cols].copy()

        for c in ["asset_id", "equipment_id", "tag_id"]:
            if c in df_out.columns:
                df_out[c] = pd.to_numeric(df_out[c], errors="coerce").astype("Int64")

        df_out["timestamp"] = pd.to_datetime(df_out["timestamp"], errors="coerce")
        df_out = df_out.dropna(subset=["timestamp"])
        df_out["timestamp"] = df_out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
        df_out["month"] = df_out["timestamp"].str[:7]

        for month, df_month in df_out.groupby("month"):
            converted_path = csv_file.with_name(f"{csv_file.stem}_{month}_converted_ids.csv")
            df_month.drop(columns=["month"]).to_csv(converted_path, index=False)
            logger.info(f"[{self.tenant}] ✅ CSV converted (month {month}): {converted_path}")
            yield converted_path

    def _upload_part_with_retries(self, part_path: Path, retries: int = MAX_RETRIES) -> bool:
        attempt = 0
        while attempt <= retries:
            try:
                self.warehouse_client.upload_csv(str(part_path))
                return True
            except Exception as e:
                logger.error(f"[{self.tenant}] ✗ Failed to send {part_path} (attempt {attempt + 1}/{retries + 1}): {e}")
                attempt += 1
        return False

    def process_converted_with_api_parallel(self, converted_path: Path, chunk_size: int = CHUNK_SIZE) -> bool:
        logger.info(f"[{self.tenant}] 🚀 Upload: {converted_path}")
        if "_part" in converted_path.stem:
            return True
        try:
            reader = pd.read_csv(converted_path, chunksize=chunk_size)
        except Exception as e:
            logger.error(f"[{self.tenant}] ✗ Error reading {converted_path}: {e}")
            return False

        part_index = 0
        futures = []
        overall_ok = True

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for chunk in reader:
                part_index += 1
                part_path = converted_path.with_name(f"{converted_path.stem}_part{part_index}.csv")
                done_marker = part_path.with_suffix(part_path.suffix + ".done")
                if done_marker.exists():
                    continue
                chunk.to_csv(part_path, index=False)
                logger.info(f"[{self.tenant}] 💾 Part {part_index} ({len(chunk)} rows)")
                futures.append((part_index, done_marker, executor.submit(self._upload_part_with_retries, part_path)))

            for part_idx, marker, fut in futures:
                try:
                    ok = fut.result()
                    if ok:
                        marker.touch()
                        logger.info(f"[{self.tenant}] ✅ Part {part_idx} completed")
                    else:
                        overall_ok = False
                        logger.error(f"[{self.tenant}] ✗ Part {part_idx} failed")
                except Exception as e:
                    overall_ok = False
                    logger.error(f"[{self.tenant}] ✗ Error in part {part_idx}: {e}", exc_info=True)

        logger.info(f"[{self.tenant}] 🔚 Upload finished: {part_index} parts")
        return overall_ok
