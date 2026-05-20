import pytest
import pandas as pd
import psycopg2
from fastapi.testclient import TestClient
from api.main import app

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "sensor_data_dev",
    "user": "integrator",
    "password": "integrator123",
}


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup(db_conn):
    yield
    cur = db_conn.cursor()
    cur.execute("DELETE FROM sensor_readings WHERE tag_id IN (SELECT id FROM tag WHERE name LIKE 'TEST_%');")
    cur.execute("DELETE FROM tag WHERE name LIKE 'TEST_%';")
    cur.execute("DELETE FROM equipment WHERE code LIKE 'test-%';")
    cur.execute("DELETE FROM asset WHERE name LIKE 'Test %';")
    db_conn.commit()
    cur.close()


# ─── Health ───────────────────────────────────────────────────────────────────

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ─── Upload validation ────────────────────────────────────────────────────────

def test_upload_wrong_extension_rejected(client):
    response = client.post(
        "/upload",
        data={"tenant": "ORION"},
        files={"file": ("test.pdf", b"fake content", "application/pdf")},
    )
    assert response.status_code == 422


def test_upload_missing_tenant_rejected(client):
    response = client.post(
        "/upload",
        files={"file": ("test.csv", b"timestamp,value\n2024-01-01,72.5", "text/csv")},
    )
    assert response.status_code == 422


# ─── Job lifecycle ────────────────────────────────────────────────────────────

def test_job_not_found(client):
    response = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_list_jobs_returns_list(client):
    response = client.get("/jobs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ─── Database ─────────────────────────────────────────────────────────────────

def test_database_connection(db_conn):
    cur = db_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tag;")
    count = cur.fetchone()[0]
    cur.close()
    assert count >= 0


def test_tables_exist(db_conn):
    cur = db_conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    assert "asset" in tables
    assert "equipment" in tables
    assert "tag" in tables
    assert "sensor_readings" in tables


def test_insert_and_query_sensor_reading(db_conn):
    cur = db_conn.cursor()

    cur.execute("INSERT INTO asset (name, industry_id, state, operation_status_id) VALUES (%s, 1, 'ACTIVE', 1) RETURNING id;", ("Test Asset Integration",))
    asset_id = cur.fetchone()[0]

    cur.execute("INSERT INTO equipment (name, code, asset_id) VALUES (%s, %s, %s) RETURNING id;", ("Test Equipment", "test-equip-001", asset_id))
    equipment_id = cur.fetchone()[0]

    cur.execute("INSERT INTO tag (name, description, signal_label, type, unit, equipment_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;",
                ("TEST_TEMP_01", "Test Temperature Sensor", "temperature", "MEASURE", "C", equipment_id))
    tag_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO sensor_readings (timestamp, value, asset_id, equipment_id, tag_id, quality)
        VALUES ('2024-06-01T00:00:00+00', 72.5, %s, %s, %s, 'saudavel');
    """, (asset_id, equipment_id, tag_id))

    db_conn.commit()

    cur.execute("SELECT value FROM sensor_readings WHERE tag_id = %s;", (tag_id,))
    row = cur.fetchone()
    cur.close()

    assert row is not None
    assert float(row[0]) == 72.5