.PHONY: test lint test-unit test-integration format docker-build docker-run docker-shell docker-clean

PYTHON ?= venv/bin/python
RUFF ?= venv/bin/ruff

docker-build:
	docker build -t pdo-daemon .

docker-run:
	docker run -d --name pdo-daemon -v $$(pwd):/app/workspace pdo-daemon

docker-shell:
	docker exec -it pdo-daemon bash

docker-clean:
	docker rm -f pdo-daemon

test-unit:
	$(PYTHON) -m pytest tests/ -v --ignore=tests/test_integration.py

test-integration:
	$(PYTHON) -m pytest tests/test_integration.py -v

test:
	$(PYTHON) -m pytest tests/ -v --cov=src/pdo --cov-report=term-missing

lint:
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/

format:
	$(RUFF) format src/ tests/
