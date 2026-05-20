# Sensor Data Integrator

A production-grade multi-tenant API for ingesting, validating, and routing industrial sensor data.

Built with **Python**, **FastAPI**, **PostgreSQL/TimescaleDB**, and **React**.

---

## Architecture

```
[React Frontend] → [Integrator API :8000] → [Data Warehouse API :8096] → [PostgreSQL/TimescaleDB]
                          ↓
                   [Statistical Validator]
                   - Structural validation
                   - Duplicate detection
                   - Timestamp range check
                   - Spike detection (MAD)
                   - Frozen sensor detection
                   - Historical duplicate check
```

### Data Hierarchy
```
Industry → Asset → Equipment → Tag → Sensor Readings
```

### Tenants
| Tenant | Segment  | Accepted Formats |
|--------|----------|-----------------|
| ORION  | Subsea   | CSV, TXT, XLSX  |
| NEXUS  | Substation | CSV           |
| ATLAS  | Subsea   | CSV, XLSX       |

---

## Tech Stack

| Layer       | Technology                        |
|-------------|-----------------------------------|
| Backend     | Python 3.12, FastAPI, Uvicorn     |
| Database    | PostgreSQL 15 + TimescaleDB       |
| Validation  | Pandas, MAD statistical analysis  |
| Frontend    | React, Vite                       |
| Container   | Docker, Docker Compose            |
| Testing     | Pytest (unit + integration)       |

---

## Getting Started

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker Desktop

### 1. Clone the repository
```bash
git clone https://github.com/your-username/sensor-data-integrator.git
cd sensor-data-integrator
```

### 2. Set up Python environment
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install python-multipart requests
```

### 3. Configure environment
```bash
cp .env.example .env
```

### 4. Start the database
```bash
docker-compose up db -d
```

### 5. Start the services

**Terminal 1 — Data Warehouse API:**
```bash
cd warehouse
python -m uvicorn app.main:app --port 8096 --reload
```

**Terminal 2 — Integrator API:**
```bash
python -m uvicorn api.main:app --reload --port 8000
```

**Terminal 3 — Frontend:**
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

---

## API Endpoints

| Method | Endpoint         | Description                    |
|--------|-----------------|--------------------------------|
| POST   | `/upload`        | Upload sensor data file        |
| GET    | `/jobs/{job_id}` | Get job status and result      |
| GET    | `/jobs`          | List all jobs                  |
| GET    | `/health`        | Health check                   |

### Upload Example
```bash
curl -X POST http://localhost:8000/upload \
  -F "tenant=ORION" \
  -F "file=@sensor_data.xlsx"
```

### Response
```json
{
  "job_id": "89a9ed9d-04e0-4904-810f-12de6b81d188",
  "tenant": "ORION",
  "status": "PENDING",
  "message": "'sensor_data.xlsx' received. Processing in background.",
  "submitted_at": "2024-01-01T00:00:00Z"
}
```

---

## Data Validation

The validator applies 6 rules in sequence:

| Rule | Description |
|------|-------------|
| Structure | Checks required columns and data types |
| Duplicates | Detects duplicate `tag_id + timestamp` within file |
| Timestamp Range | Rejects timestamps older than 10 years or in the future |
| Spike | Detects abrupt jumps using MAD (Median Absolute Deviation) |
| Frozen Sensor | Detects same value repeated N times consecutively |
| Historical Duplicate | Checks against existing database records |

Each row is classified with a quality label:

`saudavel` · `outlier` · `spike` · `congelado` · `outlier_spike` · `congelado_spike` · `outlier_congelado`

---

## Supported File Formats

### XLSX / CSV
Must contain: `timestamp`, `value`, `equipment_name`, `tagName`

### TXT (Petrobras-style)
```
Equipment : UNIT-01
Sensor Type : PRESSURE

Reg;Status;Data;Hora;Pr;
;;dd/mm/aaaa;hh:mm:ss;bar;

1;OK;01/05/2024;00:00:00;138.74;
```

---

## Running Tests

```bash
# Unit tests (no database required)
python -m pytest tests/unit/ -v

# Integration tests (requires Docker database)
python -m pytest tests/integration/ -v

# All tests
python -m pytest -v
```

---

## Project Structure

```
sensor-data-integrator/
├── api/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings and database config
│   ├── models.py            # Pydantic models
│   ├── routers/
│   │   └── upload.py        # Upload and jobs endpoints
│   └── services/
│       ├── base_service.py  # Abstract base service
│       ├── validator.py     # Statistical data validator
│       ├── orion_service.py
│       ├── nexus_service.py
│       └── atlas_service.py
├── core/
│   ├── warehouse_client.py  # HTTP client for Warehouse API
│   ├── orion_ingester.py
│   ├── nexus_ingester.py
│   └── atlas_ingester.py
├── warehouse/               # Data Warehouse API (FastAPI)
│   └── app/
│       ├── main.py
│       ├── config.py
│       └── routes.py
├── frontend/                # React + Vite
├── docker/
│   └── schema.sql           # Database schema (TimescaleDB)
├── tests/
│   ├── unit/                # Unit tests (no DB)
│   └── integration/         # Integration tests (requires DB)
├── docker-compose.yml
├── Dockerfile
└── README.md
```

---

## License

MIT
