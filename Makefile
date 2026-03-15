.PHONY: test lint test-unit test-integration format docker-build docker-run docker-shell docker-clean

docker-build:
	docker build -t pdo-daemon .

docker-run:
	docker run -d --name pdo-daemon -v $$(pwd):/app/workspace pdo-daemon

docker-shell:
	docker exec -it pdo-daemon bash

docker-clean:
	docker rm -f pdo-daemon

test-unit:
	python -m pytest tests/ -v --ignore=tests/test_integration.py

test-integration:
	python -m pytest tests/test_integration.py -v

test:
	python -m pytest tests/ -v --cov=src/pdo --cov-report=term-missing

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/
