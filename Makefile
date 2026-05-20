.PHONY: install dev warehouse api frontend worker db rabbitmq infra stop logs test

# ─── Setup ────────────────────────────────────────────────────────────────────
install:
	pip install -r requirements.txt
	pip install python-multipart requests
	cd frontend && npm install

# ─── Infrastructure ───────────────────────────────────────────────────────────
db:
	docker-compose up db -d

rabbitmq:
	docker-compose up rabbitmq -d

infra:
	docker-compose up db rabbitmq -d

stop:
	docker-compose down

logs:
	docker-compose logs -f

# ─── Services ─────────────────────────────────────────────────────────────────
warehouse:
	cd warehouse && python -m uvicorn app.main:app --port 8096 --reload

api:
	python -m uvicorn api.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

# ─── Dev (all services) ───────────────────────────────────────────────────────
dev: infra
	@echo "Starting all services..."
	@start cmd /k "cd warehouse && python -m uvicorn app.main:app --port 8096 --reload"
	@start cmd /k "python -m uvicorn api.main:app --reload --port 8000"
	@start cmd /k "cd frontend && npm run dev"

# ─── Tests ────────────────────────────────────────────────────────────────────
test:
	python -m pytest -v

test-unit:
	python -m pytest tests/unit/ -v

test-integration:
	python -m pytest tests/integration/ -v