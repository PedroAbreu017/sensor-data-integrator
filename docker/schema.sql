-- ─── Sensor Data Integrator — Database Schema ─────────────────────────────

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Industry
CREATE TABLE IF NOT EXISTS industry (
    id   BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- Operation Status
CREATE TABLE IF NOT EXISTS operation_status (
    id   BIGSERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL
);

-- Asset
CREATE TABLE IF NOT EXISTS asset (
    id                  BIGSERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    industry_id         BIGINT REFERENCES industry(id),
    state               VARCHAR(50),
    operation_status_id BIGINt REFERENCES operation_status(id)
);

-- Location
CREATE TABLE IF NOT EXISTS location (
    id             BIGSERIAL PRIMARY KEY,
    macro_location VARCHAR(100),
    micro_location VARCHAR(100),
    location_2     VARCHAR(100)
);

-- Equipment
CREATE TABLE IF NOT EXISTS equipment (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    code        VARCHAR(100),
    asset_id    BIGINT REFERENCES asset(id),
    location_id BIGINT REFERENCES location(id)
);

-- Tag
CREATE TABLE IF NOT EXISTS tag (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    description  VARCHAR(255),
    signal_label VARCHAR(100) NOT NULL,
    type         VARCHAR(50),
    unit         VARCHAR(50),
    equipment_id BIGINT REFERENCES equipment(id),
    UNIQUE (name)
);

-- Sensor Readings (hypertable)
CREATE TABLE IF NOT EXISTS sensor_readings (
    id           BIGSERIAL,
    timestamp    TIMESTAMPTZ NOT NULL,
    value        DOUBLE PRECISION NOT NULL,
    asset_id     BIGINT REFERENCES asset(id),
    equipment_id BIGINT REFERENCES equipment(id),
    tag_id       BIGINT REFERENCES tag(id),
    quality      VARCHAR(50),
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable('sensor_readings', 'timestamp', if_not_exists => TRUE);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sensor_readings_tag_id ON sensor_readings (tag_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_equipment ON sensor_readings (equipment_id, timestamp DESC);

-- Seed data
INSERT INTO operation_status (name) VALUES ('ACTIVE') ON CONFLICT DO NOTHING;
INSERT INTO industry (name) VALUES ('Energy') ON CONFLICT DO NOTHING;