import logging
import re
from pathlib import Path
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from concurrent.futures import ThreadPoolExecutor
from core.warehouse_client import DataWarehouseClient
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("integrator.orion")

APP_ENV = os.getenv("APP_ENV", "dev")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv(f"DB_NAME_SENSOR_SUBSEA_{APP_ENV.upper()}"),
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

DEFAULT_CTX = {
    "asset_name": "Orion Asset Alpha",
    "equipment_name": "subsea-unit-01",
    "equipment_code": "orion-equip-001",
}

EQUIPMENTS = {
    "UNIT-01": DEFAULT_CTX,
    "UNIT-02": DEFAULT_CTX,
    "UNIT-03": DEFAULT_CTX,
}

TAG_signal_label = {
    "TEMP_01": "temperature",
    "TEMP_02": "temperature",
    "PRESS_01": "pressure",
    "PRESS_02": "pressure",
    "FLOW_01": "flow",
    "FLOW_02": "flow",
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
                if op_row is None:
                    cur.execute("INSERT INTO operation_status (name) VALUES (%s) RETURNING id;", ("ACTIVE",))
                    op_id = cur.fetchone()[0]
                else:
                    op_id = op_row[0]

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
                    logger.info(f"🔄 Equipment already exists: {equipment_name} (id={row[0]}, asset_id={row[1]})")
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


def insert_missing_tags(missing_tags, equipment_id, signal_labels=None):
    if not missing_tags:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                values = [
                    (tag, tag, signal_labels.get(tag) if signal_labels else tag, "", "", equipment_id)
                    for tag in missing_tags
                ]
                execute_values(
                    cur,
                    """
                    INSERT INTO tag (name, description, signal_label, type, unit, equipment_id)
                    VALUES %s
                    ON CONFLICT DO NOTHING;
                    """,
                    values,
                )
            conn.commit()
        logger.info(f"✅ Tags inserted: {list(missing_tags)}")
    except Exception as e:
        logger.error(f"✗ Error inserting tags: {e}")


class OrionDataIngester:
    DB_CONFIG = DB_CONFIG

    def __init__(self, tenant="ORION", base_dir_arg="data/orion", warehouse_url=None):
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

    def _ensure_context(self, ctx: dict) -> tuple[int, int]:
        asset_id = ensure_asset(ctx["asset_name"])
        code = ctx.get("equipment_code", ctx["equipment_name"])
        equipment_id, real_asset_id = ensure_equipment(ctx["equipment_name"], asset_id, code=code)
        return real_asset_id, equipment_id

    def convert_xlsx(self, xlsx_file: Path):
        df = pd.read_excel(xlsx_file, engine="openpyxl")

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp", "value"])
        df["timestamp"] = df["timestamp"].dt.tz_convert(None).dt.strftime("%Y-%m-%dT%H:%M:%S")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])

        equipment_name_from_file = (
            df["equipment_name"].dropna().iloc[0] if "equipment_name" in df.columns else "UNIT-01"
        )
        tag = df["tagName"].dropna().iloc[0] if "tagName" in df.columns else None

        if tag is None:
            logger.error(f"[{self.tenant}] ❌ tagName not found in {xlsx_file.name}")
            return

        df["tag"] = tag
        ctx = EQUIPMENTS.get(equipment_name_from_file, DEFAULT_CTX)
        asset_id, equipment_id = self._ensure_context(ctx)

        if tag not in self.tag_map:
            signal_label = TAG_signal_label.get(tag, tag)
            insert_missing_tags([tag], equipment_id, {tag: signal_label})
            self._reload_maps()

        df["tag_id"] = df["tag"].map(self.tag_map)
        df["equipment_id"] = equipment_id
        df["asset_id"] = asset_id
        df["signal_label"] = df["tag_id"].map(self.tag_to_signal_label)
        df = df.dropna(subset=["tag_id"])
        df = df[df["value"] != 0]

        cols = [c for c in ["timestamp", "value", "asset_id", "equipment_id", "tag_id", "signal_label"] if c in df.columns]
        df_out = df[cols].copy()

        for c in ["asset_id", "equipment_id", "tag_id"]:
            if c in df_out.columns:
                df_out[c] = pd.to_numeric(df_out[c], errors="coerce").astype("Int64")

        df_out["month"] = df_out["timestamp"].str[:7]

        for month, df_month in df_out.groupby("month"):
            converted_path = xlsx_file.with_name(f"{xlsx_file.stem}_{month}_converted_ids.csv")
            df_month.drop(columns=["month"]).to_csv(converted_path, index=False)
            logger.info(f"[{self.tenant}] ✅ XLSX converted (month {month}): {converted_path}")
            yield converted_path

    def convert_csv(self, csv_file: Path):
        with open(csv_file, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
        sep = ";" if ";" in first_line else ","
        df = pd.read_csv(csv_file, sep=sep, decimal=".", on_bad_lines="skip")

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

        if "tagName" in df.columns and "value" in df.columns:
            tag = df["tagName"].dropna().iloc[0] if not df["tagName"].dropna().empty else None
            if tag is None:
                logger.error(f"[{self.tenant}] ❌ tagName not found in {csv_file.name}")
                return

            equipment_name_from_file = (
                df["equipment_name"].dropna().iloc[0] if "equipment_name" in df.columns else "UNIT-01"
            )
            df["tag"] = tag
            ctx = EQUIPMENTS.get(equipment_name_from_file, DEFAULT_CTX)
            asset_id, equipment_id = self._ensure_context(ctx)

            if tag not in self.tag_map:
                signal_label = TAG_signal_label.get(tag, tag)
                insert_missing_tags([tag], equipment_id, {tag: signal_label})
                self._reload_maps()

            df["tag_id"] = df["tag"].map(self.tag_map)
            df["equipment_id"] = equipment_id
            df["asset_id"] = asset_id
            df["signal_label"] = df["tag_id"].map(self.tag_to_signal_label)
            df = df.dropna(subset=["tag_id", "value"])
            df = df[df["value"] != 0]

            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"])
            df["timestamp"] = df["timestamp"].dt.tz_convert(None).dt.strftime("%Y-%m-%dT%H:%M:%S")

            cols = [c for c in ["timestamp", "value", "asset_id", "equipment_id", "tag_id", "signal_label"] if c in df.columns]
            df_out = df[cols].copy()

            for c in ["asset_id", "equipment_id", "tag_id"]:
                if c in df_out.columns:
                    df_out[c] = pd.to_numeric(df_out[c], errors="coerce").astype("Int64")

            df_out["month"] = df_out["timestamp"].str[:7]
            for month, df_month in df_out.groupby("month"):
                converted_path = csv_file.with_name(f"{csv_file.stem}_{month}_converted_ids.csv")
                df_month.drop(columns=["month"]).to_csv(converted_path, index=False)
                logger.info(f"[{self.tenant}] ✅ CSV converted (month {month}): {converted_path}")
                yield converted_path
            return

        for col in ["timestamp", "ts", "E3TimeStamp"]:
            if col in df.columns:
                df.rename(columns={col: "timestamp"}, inplace=True)
                break
        if "timestamp" not in df.columns:
            df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)

        df = df.melt(id_vars=["timestamp"], var_name="tag", value_name="value")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp", "value"])

        asset_id, equipment_id = self._ensure_context(DEFAULT_CTX)

        missing_tags = [t for t in df["tag"].unique() if t not in self.tag_map]
        if missing_tags:
            signal_labels = {t: TAG_signal_label.get(t) for t in missing_tags}
            insert_missing_tags(missing_tags, equipment_id, signal_labels)
            self._reload_maps()

        df["tag_id"] = df["tag"].map(self.tag_map)
        df["equipment_id"] = equipment_id
        df["asset_id"] = asset_id
        df["signal_label"] = df["tag_id"].map(self.tag_to_signal_label)
        df = df.dropna(subset=["tag_id"])
        df = df[df["value"] != 0]

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

    def _read_txt(self, file: Path) -> pd.DataFrame:
        encodings = ["latin-1", "cp1252", "utf-8"]
        for encoding in encodings:
            try:
                with open(file, "r", encoding=encoding) as f:
                    lines = [line.rstrip() for line in f if line.strip()]
                if not lines:
                    continue

                header_idx = None
                for idx, line in enumerate(lines):
                    if "Reg;" in line and ";" in line:
                        parts = [p.strip() for p in line.split(";")]
                        if "Reg" in parts and "Data" in parts and "Hora" in parts:
                            header_idx = idx
                            break

                if header_idx is None:
                    continue

                headers = [h.strip() for h in lines[header_idx].split(";") if h.strip()]
                data_start = header_idx + 2

                records = []
                for line in lines[data_start:]:
                    line_stripped = line.strip()
                    if re.match(r"^[\d\-A-Z]+;", line_stripped):
                        values = [v.strip() for v in line_stripped.split(";")]
                        while len(values) < len(headers):
                            values.append(None)
                        records.append(dict(zip(headers, values[:len(headers)])))

                if records:
                    df = pd.DataFrame(records)
                    df.columns = [c.strip() for c in df.columns]
                    return df

            except FileNotFoundError:
                raise
            except Exception:
                continue

        logger.warning(f"⚠️ Empty or unreadable file: {file.name}")
        return pd.DataFrame()

    def _parse_data(self, df: pd.DataFrame, file: Path) -> pd.DataFrame:
        try:
            if df.empty:
                return pd.DataFrame()

            sensor_type = "PRESS_01"
            if "TEMP" in file.name.upper():
                sensor_type = "TEMP_01"
            elif "FLOW" in file.name.upper():
                sensor_type = "FLOW_01"

            df.columns = [c.strip().capitalize() for c in df.columns]

            tag_column = None
            if "Pr" in df.columns:
                df.rename(columns={"Pr": sensor_type}, inplace=True)
                tag_column = sensor_type
            elif "Tp" in df.columns:
                df.rename(columns={"Tp": sensor_type}, inplace=True)
                tag_column = sensor_type

            if tag_column is None or "Data" not in df.columns or "Hora" not in df.columns:
                return pd.DataFrame()

            df["timestamp"] = pd.to_datetime(
                df["Data"].astype(str).str.strip() + " " + df["Hora"].astype(str).str.strip(),
                dayfirst=True, errors="coerce",
            )
            df = df.dropna(subset=["timestamp"])
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")

            equipment_name_from_file = None
            try:
                with open(file, "r", encoding="latin-1") as f:
                    for line in f:
                        if "Equipment" in line or "Unit" in line:
                            equipment_name_from_file = line.split(":")[-1].strip()
                            break
            except Exception:
                pass

            ctx = EQUIPMENTS.get(equipment_name_from_file, DEFAULT_CTX)
            asset_id, equipment_id = self._ensure_context(ctx)

            if tag_column not in self.tag_map:
                insert_missing_tags([tag_column], equipment_id, {tag_column: TAG_signal_label.get(tag_column)})
                self._reload_maps()

            tag_id = self.tag_map.get(tag_column)
            if tag_id is None:
                return pd.DataFrame()

            records = []
            for _, row in df.iterrows():
                ts = row.get("timestamp")
                if not ts or pd.isna(ts):
                    continue
                val = str(row.get(tag_column, "")).replace(",", ".").strip()
                try:
                    records.append({
                        "timestamp": ts,
                        "tag_id": tag_id,
                        "value": float(val),
                        "asset_id": asset_id,
                        "equipment_id": equipment_id,
                        "signal_label": TAG_signal_label.get(tag_column),
                    })
                except ValueError:
                    continue

            return pd.DataFrame(records) if records else pd.DataFrame()

        except Exception as e:
            logger.error(f"❌ Error parsing data: {e}", exc_info=True)
            return pd.DataFrame()

    def _upload_part_with_retries(self, part_path: Path, retries: int = MAX_RETRIES) -> bool:
        attempt = 0
        while attempt <= retries:
            try:
                self.warehouse_client.upload_csv(str(part_path))
                return True
            except Exception as e:
                logger.error(f"✗ Failed to send {part_path} (attempt {attempt + 1}/{retries + 1}): {e}")
                attempt += 1
        return False

    def _process_converted_with_api_parallel(self, converted_path: Path, chunk_size: int = CHUNK_SIZE) -> bool:
        logger.info(f"[{self.tenant}] 🚀 Upload: {converted_path.name}")
        if "_part" in converted_path.stem:
            return True
        try:
            reader = pd.read_csv(converted_path, chunksize=chunk_size)
        except Exception as e:
            logger.error(f"✗ Error reading {converted_path}: {e}")
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
